# -*- coding: utf-8 -*-
#
#  IPTVExtMoviePlayer
#
#  $Id$
#
# 

###################################################
# LOCAL import
###################################################
from Plugins.Extensions.IPTVPlayer.iptvdm.iptvdh import DMHelper
from Plugins.Extensions.IPTVPlayer.tools.iptvtypes import strwithmeta
from Plugins.Extensions.IPTVPlayer.components.cover import Cover3
from Plugins.Extensions.IPTVPlayer.tools.iptvtools import printDBG, printExc, GetIPTVDMImgDir, GetBinDir, GetSubtitlesDir, eConnectCallback, \
                                                          GetE2VideoAspectChoices, GetE2VideoAspect, SetE2VideoAspect, GetE2VideoPolicyChoices, \
                                                          GetE2VideoPolicy, SetE2VideoPolicy, GetDefaultLang, GetPolishSubEncoding, E2PrioFix, iptv_system, \
                                                          GetE2AudioCodecMixOption, SetE2AudioCodecMixOption
from Plugins.Extensions.IPTVPlayer.tools.iptvsubtitles import IPTVSubtitlesHandler
from Plugins.Extensions.IPTVPlayer.tools.iptvmoviemetadata import IPTVMovieMetaDataHandler
from Plugins.Extensions.IPTVPlayer.components.iptvplayerinit import TranslateTXT as _
from Plugins.Extensions.IPTVPlayer.components.iptvsubdownloader import IPTVSubDownloaderWidget
from Plugins.Extensions.IPTVPlayer.components.iptvsubsimpledownloader import IPTVSubSimpleDownloaderWidget
from Plugins.Extensions.IPTVPlayer.components.iptvchoicebox import IPTVChoiceBoxWidget, IPTVChoiceBoxItem
from Plugins.Extensions.IPTVPlayer.components.iptvdirbrowser import IPTVFileSelectorWidget
from Plugins.Extensions.IPTVPlayer.components.configextmovieplayer import ConfigExtMoviePlayerBase, ConfigExtMoviePlayer
from Plugins.Extensions.IPTVPlayer.libs.pCommon import CParsingHelper
###################################################

###################################################
# FOREIGN import
###################################################
from enigma import eServiceReference, eConsoleAppContainer, getDesktop, eTimer, eLabel, gFont, ePoint, eSize
from Screens.Screen import Screen
from Screens.ChoiceBox import ChoiceBox
from Components.AVSwitch import AVSwitch
from Components.ActionMap import ActionMap
from Components.config import config
from Components.Label import Label
from Components.ProgressBar import ProgressBar

from Components.config import config # temporary player should not use config directly
from Screens.MessageBox import MessageBox
from Tools.LoadPixmap import LoadPixmap
from Tools.BoundFunction import boundFunction
from Tools.Directories import fileExists
from skin import parseColor, parseFont

from datetime import timedelta
try:
    try:    import json
    except: import simplejson as json
except:
    printExc()
from os import chmod as os_chmod, path as os_path
import re
import time
###################################################

class ExtPlayerCommandsDispatcher():
    def __init__(self, owner):
        self.owner = owner
        
        #SEEK_SPEED_MAP = [0.125, 0.25, 0.5, 0, 2, 4, 8, 16, 32, 64, 128]
        self.SEEK_SPEED_MAP = []
        for item in reversed(config.seek.speeds_slowmotion.value):
            self.SEEK_SPEED_MAP.append(1.0 / float(item))
        self.SEEK_SPEED_MAP.append(0)
        for item in config.seek.speeds_forward.value:
            self.SEEK_SPEED_MAP.append( item )
        self.speedIdx = self.SEEK_SPEED_MAP.index(0)
        
    def doAddTriggers(self, arg): self.extPlayerSendCommand('ADD_TRIGGERS', arg)
        
    def stop(self):
        self.extPlayerSendCommand('PLAYBACK_STOP')
        self.owner = None
        
    def play(self): 
        self.extPlayerSendCommand('PLAYBACK_CONTINUE')
        self.speedIdx = self.SEEK_SPEED_MAP.index(0)
    def pause(self):            
        self.extPlayerSendCommand('PLAYBACK_PAUSE')
        self.speedIdx = self.SEEK_SPEED_MAP.index(0)
        
    def setAudioTrack(self, id):
        self.extPlayerSendCommand('PLAYBACK_SET_AUDIO_TRACK', id, False)
        
    def setDownloadFileTimeout(self, timeout):
        self.extPlayerSendCommand('PLAYBACK_SET_DOWNLOAD_FILE_TIMEOUT', timeout, False)
    
    def doSeek(self, diff):       
        self.extPlayerSendCommand('PLAYBACK_SEEK_RELATIVE', '%d' %diff)
        self.speedIdx = self.SEEK_SPEED_MAP.index(0)
    def doGoToSeek(self, arg):       
        self.extPlayerSendCommand('PLAYBACK_SEEK_ABS', arg)
        self.speedIdx = self.SEEK_SPEED_MAP.index(0)
    def doSeekFwd(self, arg):    self.extPlayerSendCommand('PLAYBACK_FASTFORWARD', arg)
    def doSlowMotion(self, arg): self.extPlayerSendCommand('PLAYBACK_SLOWMOTION', arg)
    
    def doUpdateInfo(self):
        self.extPlayerSendCommand('PLAYBACK_LENGTH', '', False)
        self.extPlayerSendCommand('PLAYBACK_CURRENT_TIME', '', False)
        
    ##############################################
    
    def seekFwd(self):
        printDBG('seekFwd skipped')
        return
        self.speedIdx += 1
        self.tipMode()
    def seekBack(self):
        printDBG('seekBack skipped')
        return
        self.speedIdx -= 1
        self.tipMode()
    def tipMode(self):
        printDBG("ExtPlayerCommandsDispatcher.tipMode speedIdx[%d]" % self.speedIdx)
        if self.speedIdx >= len(self.SEEK_SPEED_MAP): self.speedIdx = len(self.SEEK_SPEED_MAP) - 1
        elif self.speedIdx < 0: self.speedIdx = 0
        val = self.SEEK_SPEED_MAP[self.speedIdx]
        printDBG("ExtPlayerCommandsDispatcher.tipMode val[%r]" % val)
        if 0 == val:  self.play()
        elif 1 < val:
            if 'eplayer' == self.owner.player: val -= 1
            self.doSeekFwd(str(val))
        else: self.doSlowMotion(str(int(1.0 / val)))
    
    def extPlayerSendCommand(self, cmd, arg='', getStatus=True):
        if None != self.owner: 
            self.owner.extPlayerSendCommand(cmd, arg)
            if getStatus: 
                self.owner.extPlayerSendCommand("PLAYBACK_INFO", '')


class IPTVExtMoviePlayer(Screen):
    
    def __prepareSkin(self):
        
        self.subConfig = self.configObj.getSubtitleFontSettings()
        
        if self.subConfig['wrapping_enabled']:
            self.subLinesNum = 1
        else:
            self.subLinesNum = 4
        
        sub = self.subConfig
        if self.subLinesNum > 1 or 'transparent' != self.subConfig['background']:
            valign = "center"
        else:
            valign = sub['box_valign']
        subSkinPart = ' valign="%s" foregroundColor="%s" font="%s;%s" ' % (valign, sub['font_color'], sub['font'], sub['font_size'])
        if 'border' in sub:
            subSkinPart += ' borderColor="%s" borderWidth="%s" ' % (sub['border']['color'], sub['border']['width']) 
        if 'shadow' in sub:
            subSkinPart += ' shadowColor="%s" shadowOffset="%s,%s" ' % (sub['shadow']['color'], sub['shadow']['xoffset'], sub['shadow']['yoffset']) 
        subSkinPart += ' backgroundColor="%s" ' % (sub['background'])
        
        if self.subLinesNum > 1:
            subSkinPart += ' noWrap="1" '
        
        subSkinPart = '<widget name="subLabel{0}" position="10,%d" size="%d,%d" zPosition="1" halign="center" %s/>' % (getDesktop(0).size().height()-sub['pos']-sub['box_height'], getDesktop(0).size().width()-20, sub['box_height'], subSkinPart)
        subSkin = ''
        for idx in range(self.subLinesNum):
            subSkin += subSkinPart.format(idx+1)
            
        skin = """
        <screen name="IPTVExtMoviePlayer"    position="center,center" size="%d,%d" flags="wfNoBorder" backgroundColor="#FFFFFFFF" >
                <widget name="logoIcon"           position="0,0"           size="160,40"  zPosition="4"             transparent="1" alphatest="blend" />
                <widget name="playbackInfoBaner"  position="0,30"          size="650,77"  zPosition="2" pixmap="%s" transparent="1" alphatest="blend" />
                <widget name="progressBar"        position="94,54"         size="544,7"   zPosition="4" pixmap="%s" transparent="1" borderWidth="1" borderColor="#888888" />
                <widget name="bufferingBar"       position="94,54"         size="544,7"   zPosition="3" pixmap="%s" borderWidth="1" borderColor="#888888" />
                <widget name="statusIcon"         position="20,45"         size="40,40"   zPosition="4"             transparent="1" alphatest="blend" />
                
                <widget name="goToSeekPointer"    position="94,0"          size="150,60"  zPosition="8" pixmap="%s" transparent="1" alphatest="blend" />
                <widget name="goToSeekLabel"      noWrap="1" position="94,0"          size="150,40"  zPosition="9" transparent="1" foregroundColor="white"     backgroundColor="#251f1f1f" font="Regular;24" halign="center" valign="center"/>
                <widget name="infoBarTitle"       noWrap="1" position="82,30"         size="568,23"  zPosition="3" transparent="1" foregroundColor="white"     backgroundColor="#251f1f1f" font="Regular;18" halign="center" valign="center"/>
                <widget name="currTimeLabel"      noWrap="1" position="94,62"         size="120,30"  zPosition="3" transparent="1" foregroundColor="#66ccff"   backgroundColor="#251f1f1f" font="Regular;24" halign="left"   valign="top"/>
                <widget name="lengthTimeLabel"    noWrap="1" position="307,62"        size="120,30"  zPosition="3" transparent="1" foregroundColor="#999999"   backgroundColor="#251f1f1f" font="Regular;24" halign="center" valign="top"/>
                <widget name="remainedLabel"      noWrap="1" position="518,62"        size="120,30"  zPosition="3" transparent="1" foregroundColor="#66ccff"   backgroundColor="#251f1f1f" font="Regular;24" halign="right"  valign="top"/>
                
                <widget name="subSynchroIcon"     position="0,0"           size="180,66"  zPosition="4" transparent="1" alphatest="blend" />
                <widget name="subSynchroLabel"    position="1,3"           size="135,50"  zPosition="5" transparent="1" foregroundColor="white"      backgroundColor="transparent" font="Regular;24" halign="center"  valign="center"/>
                
                %s
        </screen>""" % ( getDesktop(0).size().width(), 
                         getDesktop(0).size().height(),
                         GetIPTVDMImgDir("playback_banner.png"),
                         GetIPTVDMImgDir("playback_progress.png"),
                         GetIPTVDMImgDir("playback_buff_progress.png"),
                         GetIPTVDMImgDir('playback_pointer.png'),
                         subSkin
                         ) ##00000000 bottom
        sub = None
        return skin
    
    def __init__(self, session, filesrcLocation, FileName, lastPosition=None, player='eplayer', additionalParams={}):
        # 'gstplayer'
        self.configObj = ConfigExtMoviePlayerBase()
        self.skin = self.__prepareSkin()
        Screen.__init__(self, session)
        self.skinName = "IPTVExtMoviePlayer"
        
        self.player = player
        if 'gstplayer' == self.player: 
            self.playerName = _("external gstplayer")
            self.gstAdditionalParams = {}
            self.gstAdditionalParams['download-buffer-path'] = additionalParams.get('download-buffer-path', '') # File template to store temporary files in, should contain directory and XXXXXX
            self.gstAdditionalParams['ring-buffer-max-size'] = additionalParams.get('ring-buffer-max-size', 0) # in MB
            self.gstAdditionalParams['buffer-duration']      = additionalParams.get('buffer-duration', -1) # in s
            self.gstAdditionalParams['buffer-size']          = additionalParams.get('buffer-size', 0) # in KB
            self.gstAdditionalParams['file-download-timeout']= additionalParams.get('file-download-timeout', 0) # in MS
            self.gstAdditionalParams['file-download-live']   = additionalParams.get('file-download-live', False) # True or False
        else: self.playerName = _("external eplayer3")

        self.session.nav.playService(None) # current service must be None to give free access to DVB Audio and Video Sinks
        self.fileSRC      = strwithmeta(filesrcLocation)
        self.title        = FileName
        self.hostName     = additionalParams.get('host_name', '')
        if lastPosition:
            self.lastPosition = lastPosition
        else:
            self.lastPosition = 0 
        self.downloader = additionalParams.get('downloader', None)
        self.externalSubTracks = additionalParams.get('external_sub_tracks', []) #[{'title':'', 'lang':'', 'url':''}, ...]
        
        printDBG('IPTVExtMoviePlayer.__init__ lastPosition[%r]' % self.lastPosition)
        
        self.extPlayerCmddDispatcher = ExtPlayerCommandsDispatcher(self)
        
        self["actions"] = ActionMap(['IPTVAlternateVideoPlayer', 'MoviePlayerActions', 'MediaPlayerActions', 'MediaPlayerSeekActions', 'WizardActions'],
            {
                "leavePlayer"  : self.key_stop,
                'play'         : self.key_play,
                'pause'        : self.key_pause,
                'exit'         : self.key_exit,
                'back'         : self.key_exit,
                'info'         : self.key_info,
                'seekdef:1'    : self.key_seek1,
                'seekdef:3'    : self.key_seek3,
                'seekdef:4'    : self.key_seek4,
                'seekdef:6'    : self.key_seek6,
                'seekdef:7'    : self.key_seek7,
                'seekdef:9'    : self.key_seek9,
                'seekFwd'      : self.key_seekFwd,
                'seekBack'     : self.key_seekBack,
                'left_press'   : self.key_left_press,
                'left_repeat'  : self.key_left_repeat,
                'rigth_press'  : self.key_rigth_press,
                'rigth_repeat' : self.key_rigth_repeat,
               
                'up_press'     : self.key_up_press,
                'up_repeat'    : self.key_up_repeat,
                'down_press'   : self.key_down_press,
                'down_repeat'  : self.key_down_repeat,
                
                'ok'           : self.key_ok,
                'subtitles'    : self.key_subtitles,
                'audio'        : self.key_audio,
                'videooptions' : self.key_videooption,
                'menu'         : self.key_menu,
            }, -1)
        
        self.onClose.append(self.__onClose)
        self.onShow.append(self.onStart)
        #self.onLayoutFinish.append(self.onStart)
        
        self.console = None
        
        self.isClosing = False
        self.responseData = ""
        
        # playback info
        # GUI
        self.updateInfoTimer = eTimer()
        self.updateInfoTimer_conn = eConnectCallback(self.updateInfoTimer.timeout, self.updateInfo)
        
        # playback info bar gui elements
        self['logoIcon']          = Cover3()
        self['playbackInfoBaner'] = Cover3()
        self['statusIcon']        = Cover3()
        self['progressBar']       = ProgressBar()
        self['bufferingBar']      = ProgressBar()
        self['goToSeekPointer']   = Cover3() 
        self['infoBarTitle']      = Label(self.title)
        self['goToSeekLabel']     = Label("0:00:00")
        self['currTimeLabel']     = Label("0:00:00")
        self['remainedLabel']     = Label("-0:00:00")
        self['lengthTimeLabel']   = Label("0:00:00")
        
        # for subtitles
        for idx in range(self.subLinesNum):
            #printf('>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> ' % ('subLabel%d'%(idx+1)))
            self['subLabel%d'%(idx+1)] = Label(" ")
        self.hideSubtitles()
        self.subHandler = {}
        self.subHandler['current_sub_time_ms'] = -1
        self.subHandler['handler'] = IPTVSubtitlesHandler()
        self.subHandler['enabled'] = False
        self.subHandler['timer']   = eTimer()
        self.subHandler['timer_conn '] =  eConnectCallback(self.subHandler['timer'].timeout, self.updatSubtitlesTime)
        self.subHandler['latach_time'] = -1
        self.subHandler['last_time']   = -1
        self.subHandler['marker']      = None
        self.subHandler['synchro']     = {'visible':False, 'guiElemNames':['subSynchroLabel', 'subSynchroIcon'], 'icon':None}
        self['subSynchroLabel']        = Label("0.0s")
        self['subSynchroIcon']         = Cover3() 
        try: self.subHandler['synchro']['icon'] = LoadPixmap( GetIPTVDMImgDir("sub_synchro.png") )
        except: printExc()
        self.hideSubSynchroControl()
        
        # VIDEO options
        self.defVideoOptions  = {'aspect':None, 'aspect_choices':[], 'policy':None, 'policy_choices':[], 'policy2':None, 'policy2_choices':[]}
        self.videoOptSetters  = {'aspect':SetE2VideoAspect, 'policy':SetE2VideoPolicy, 'policy2':SetE2VideoPolicy} 
        self.currVideoOptions = {'aspect':None, 'policy':None, 'policy2':None}
        
        # AUDIO options
        self.defAudioOptions  = {'ac3':None, 'aac':None}
        
        # meta data
        self.metaHandler = IPTVMovieMetaDataHandler( self.hostName, self.title, self.fileSRC )
        
        # goto seek  timer
        self.playback = {}
        self.playback['GoToSeekTimer'] = eTimer()
        self.playback['GoToSeekTimer_conn'] = eConnectCallback(self.playback['GoToSeekTimer'].timeout, self.doGoToSeek)
        
        self.playback.update( {'CurrentTime':    0,
                               'Length':         0,
                               'LengthFromPlayerReceived': False,
                               'GoToSeekTime':      0,
                               'StartGoToSeekTime': 0,
                               'GoToSeeking':    False,
                               'IsLive':         False,
                               'Status':         None,
                               'VideoTrack':     {},
                               'AudioTrack':     {},
                               'AudioTracks':   [],
                              } )
        # load pixmaps for statusIcon
        self.playback['logoIcon'] = None
        self.playback['statusIcons'] = {'Play':None, 'Pause':None, 'FastForward':None, 'SlowMotion':None}
        try:
            self.playback['statusIcons']['Play']        = LoadPixmap( GetIPTVDMImgDir("playback_a_play.png") )
            self.playback['statusIcons']['Pause']       = LoadPixmap( GetIPTVDMImgDir("playback_a_pause.png") )
            self.playback['statusIcons']['FastForward'] = LoadPixmap( GetIPTVDMImgDir("playback_a_ff.png") )
            self.playback['statusIcons']['SlowMotion']  = self.playback['statusIcons']['FastForward']
            if 'gstplayer' == self.player: 
                self.playback['logoIcon']               = LoadPixmap( GetIPTVDMImgDir("playback_gstreamer_logo.png") )
            else: self.playback['logoIcon']             = LoadPixmap( GetIPTVDMImgDir("playback_ffmpeg_logo.png") )
        except:
            printExc()
        
        # show hide info bar functionality
        self.goToSeekRepeatCount = 0
        self.goToSeekStep = 0
        self.playbackInfoBar = {'visible':False, 'blocked':False, 'guiElemNames':['playbackInfoBaner', 'progressBar', 'bufferingBar', 'goToSeekPointer', 'goToSeekLabel', 'infoBarTitle', 'currTimeLabel', 'remainedLabel', 'lengthTimeLabel', 'statusIcon', 'logoIcon'] }
        self.playbackInfoBar['timer'] = eTimer()
        self.playbackInfoBar['timer_conn'] = eConnectCallback(self.playbackInfoBar['timer'].timeout, self.hidePlaybackInfoBar)
        
        self.isStarted = False
        self.hidePlaybackInfoBar()
        
        self.waitEOSAbortedFix = {'EOSaborted_received': False, 'poll_received': False, 'timer': None}
        self.waitEOSAbortedFix['timer'] = eTimer()
        self.waitEOSAbortedFix['timer_conn'] = eConnectCallback(self.waitEOSAbortedFix['timer'].timeout, self.waitEOSAbortedFixTimeoutCallback)
        
        self.waitCloseFix = {'waiting':False}
        self.waitCloseFix['timer'] = eTimer()
        self.waitCloseFix['timer_conn'] = eConnectCallback(self.waitCloseFix['timer'].timeout, self.waitCloseTimeoutCallback)
        
        self.isCloseRequestedByUser = False
        self.playerBinaryInfo = {'version':None, 'data':''}
        self.messageQueue = []
        self.underMessage = False
        
        try: self.autoHideTime = 1000 * int(self.configObj.getInfoBarTimeout())
        except: self.autoHideTime = 1000
        
        self.fatalErrorOccurs  = False
        self.delayedClosure    = None
        self.childWindowsCount = 0
        
        self.workconsole = None
        
    def showMenuOptions(self):
        printDBG("showMenuOptions")
        options = []
        options.append(IPTVChoiceBoxItem(_("External movie player config"), "", "menu"))
        options.append(IPTVChoiceBoxItem(_("Subtitles"), "", "subtitles"))
        options.append(IPTVChoiceBoxItem(_("Video options"), "", "video_options"))
        
        if len(options):
            self.openChild(boundFunction(self.childClosed, self.showMenuOptionsCallback), IPTVChoiceBoxWidget, {'width':400, 'height':240, 'current_idx':0, 'title':_("Menu"), 'options':options})
        
    def showMenuOptionsCallback(self, ret=None):
        printDBG("showMenuOptionsCallback ret[%r]" % [ret])
        if not isinstance(ret, IPTVChoiceBoxItem): return
        
        if "menu" == ret.privateData:
            self.runConfigMoviePlayer()
        elif "subtitles" == ret.privateData:
            self.selectSubtitle()
        elif "video_options" == ret.privateData:
            self.selectVideoOptions()
        
    def runConfigMoviePlayer(self):
        printDBG("runConfigMoviePlayerCallback")
        self.openChild(boundFunction(self.childClosed, self.runConfigMoviePlayerCallback), ConfigExtMoviePlayer, True)
        
    def runConfigMoviePlayerCallback(self, confgiChanged=False):
        printDBG("runConfigMoviePlayerCallback confgiChanged[%s]" % confgiChanged)
        if not confgiChanged: return
        
        # change subtitles settings
        self.subConfig = self.configObj.getSubtitleFontSettings()
        sub = self.subConfig
        
        for idx in range(self.subLinesNum):
            subLabel = "subLabel%d"%(idx+1)
            self[subLabel].instance.setFont( gFont(sub['font'], sub['font_size']) )
            self[subLabel].instance.setForegroundColor( parseColor(sub['font_color']) )
            self[subLabel].instance.setBackgroundColor( parseColor(sub['background']) )

            if 'border' in sub:
                self[subLabel].instance.setBorderColor( parseColor(sub['border']['color']) )
                self[subLabel].instance.setBorderWidth( sub['border']['width'] )
            else:
                try:
                    tmp = dir(eLabel)
                    if 'setBorderColor' in tmp:
                        self[subLabel].instance.setBorderWidth( 0 )
                except: printExc()
            
            if 'shadow' in sub:
                self[subLabel].instance.setShadowColor( parseColor(sub['shadow']['color']) )
                self[subLabel].instance.setShadowOffset( ePoint(sub['shadow']['xoffset'], sub['shadow']['yoffset']) )
            else:
                self[subLabel].instance.setShadowOffset( ePoint(0, 0) )
                self[subLabel].instance.setShadowColor( parseColor("#ff111111") )
            
            if self.subLinesNum > 1 or 'transparent' != self.subConfig['background']:
                self[subLabel].instance.setVAlign(1)
            else:
                try:
                    valignMap = {'bottom':2,'center':1, 'top':0}
                    self[subLabel].instance.setVAlign(valignMap.get(sub['box_valign'], 2))
                    
                    self[subLabel].instance.resize(eSize(getDesktop(0).size().width()-20, sub['box_height']))
                    self[subLabel].resize(eSize(getDesktop(0).size().width()-20, sub['box_height']))
                    self[subLabel].move( ePoint(10, getDesktop(0).size().height()-sub['pos']-sub['box_height']) )
                    self[subLabel].instance.move( ePoint(10, getDesktop(0).size().height()-sub['pos']-sub['box_height']) )
                except:
                    printExc()
            self.setSubtitlesText(" ", False)
        if -1 != self.subHandler['current_sub_time_ms']:
            self.updateSubtitles(self.subHandler['current_sub_time_ms'], True)
        sub = None
        
        # set video options
        videoOptionChange = False
        videoOptions = ['aspect', 'policy', 'policy2']
        playerDefOptions = self.configObj.getDefaultPlayerVideoOptions()
        for opt in videoOptions:
            playerVal = playerDefOptions[opt]
            metaVal   = self.metaHandler.getVideoOption(opt)
            currVal   = self.currVideoOptions[opt]
            defVal    = self.defVideoOptions[opt]
            
            printDBG(">>>>>>>>>>>>> 0 [%s]" % (metaVal) )
            if None == metaVal:
                printDBG(">>>>>>>>>>>>> A [%s] [%s]" % (currVal, playerVal) )
                if currVal != playerVal:
                    printDBG(">>>>>>>>>>>>> B")
                    if None == playerVal:
                        self.currVideoOptions[opt] = defVal
                    else:
                        self.currVideoOptions[opt] = playerVal
                    videoOptionChange = True
        
        if videoOptionChange:
            self.applyVideoOptions(self.currVideoOptions)
        
        # set auto hide options
        try: self.autoHideTime = 1000 * int(self.configObj.getInfoBarTimeout())
        except: self.autoHideTime = 1000
        
    def getE2AudioOptions(self):
        defAudioOptions  = {'ac3': GetE2AudioCodecMixOption('ac3'), 
                            'aac': GetE2AudioCodecMixOption('aac'), 
                           }
        printDBG(">>>>>>>>>>>>>>>>>>>>> getE2AudioOptions[%s]" % defAudioOptions)
        return defAudioOptions
        
    def getE2VideoOptions(self):
        defVideoOptions  = {'aspect':         GetE2VideoAspect(), 
                            'aspect_choices': GetE2VideoAspectChoices(), 
                            'policy':         GetE2VideoPolicy(), 
                            'policy_choices': GetE2VideoPolicyChoices(), 
                            'policy2':        GetE2VideoPolicy('2'), 
                            'policy2_choices':GetE2VideoPolicyChoices(),
                            'active':         None
                           }
        printDBG(">>>>>>>>>>>>>>>>>>>>> getE2VideoOptions[%s]" % defVideoOptions)
        return defVideoOptions
        
    def applyVideoOptions(self, newOptions):
        printDBG("applyVideoOptions newOptions[%s] ")
        options = ['aspect', 'policy', 'policy2']
        for opt in options:
            val = newOptions.get(opt, None)
            if None != val:
                self.videoOptSetters[opt](val)
        
    def selectVideoOptions(self):
        printDBG("selectVideoOptions")
        options = []
        currIdx = 0
        optionsTab = [{'title':_('Policy'), 'name': 'policy'}, {'title':_('Policy2'), 'name': 'policy2'}, {'title':_('Aspect'), 'name': 'aspect'}]
        for option in optionsTab:
            if len(self.defVideoOptions[option['name']+'_choices' ]) < 2: continue
            if None == self.defVideoOptions[option['name']]: continue
            if self.defVideoOptions['active'] == option['name']:
                currIdx = len(options)
            options.append(IPTVChoiceBoxItem(option['title'], "", option["name"]))
        
        if len(options):
            self.openChild(boundFunction(self.childClosed, self.selectVideoOptionsCallback), IPTVChoiceBoxWidget, {'width':400, 'current_idx':currIdx, 'title':_("Select video option"), 'options':options})
        
    def selectVideoOptionsCallback(self, ret=None):
        printDBG("selectVideoOptionsCallback ret[%r]" % [ret])
        if not isinstance(ret, IPTVChoiceBoxItem): return
        options = []
        currIdx = 0

        option = ret.privateData
        self.defVideoOptions['active'] = option
        
        choices = self.defVideoOptions['%s_choices' % option]
        currValue = self.currVideoOptions[option]
        if None == currValue: currValue = self.defVideoOptions[option]
        
        for item in choices:
            if item == currValue:
                currIdx = len(options)
            options.append(IPTVChoiceBoxItem(_(item), "", item))
        self.openChild(boundFunction(self.childClosed, self.selectVideoOptionCallback), IPTVChoiceBoxWidget, {'selection_changed':self.videoOptionSelectionChanged, 'width':300, 'current_idx':currIdx, 'title':_("Select %s") % ret.name, 'options':options})

    def videoOptionSelectionChanged(self, ret=None):
        printDBG("videoOptionSelectionChanged ret[%s]" % [ret])
        if isinstance(ret, IPTVChoiceBoxItem):
            newOptions = dict(self.currVideoOptions)
            newOptions[self.defVideoOptions['active']] = ret.privateData
            self.applyVideoOptions(newOptions)
        
    def selectVideoOptionCallback(self, ret=None):
        printDBG("selectVideoOptionsCallback ret[%r]" % [ret])
        if isinstance(ret, IPTVChoiceBoxItem):
            self.metaHandler.setVideoOption(self.defVideoOptions['active'], ret.privateData)
            self.currVideoOptions[self.defVideoOptions['active']] = ret.privateData
        else:
            ret = IPTVChoiceBoxItem("", "", self.currVideoOptions[self.defVideoOptions['active']] )
        self.videoOptionSelectionChanged(ret)
        self.selectVideoOptions()
        
    def selectAudioTrack(self):
        printDBG("selectAudioTrack")
        tracksTab = self.playback['AudioTracks']
        if len(tracksTab):
            options = []
            printDBG(">>>>>>>>>>>> AudioTrack[%s]" % self.playback['AudioTrack'])
            currentId = self.playback['AudioTrack'].get('id', -1)
            currIdx = 0
            for trackIdx in range(len(tracksTab)):
                name = '[{0}] {1}'.format(tracksTab[trackIdx]['name'], tracksTab[trackIdx]['encode'])
                item = IPTVChoiceBoxItem(name, "", {'track_id':tracksTab[trackIdx]['id'], 'track_idx':trackIdx})
                if tracksTab[trackIdx]['id'] == currentId:
                    item.type = IPTVChoiceBoxItem.TYPE_ON
                    currIdx = trackIdx
                else:
                    item.type = IPTVChoiceBoxItem.TYPE_OFF
                options.append( item )
            self.openChild(boundFunction(self.childClosed, self.selectAudioTrackCallback), IPTVChoiceBoxWidget, {'width':400, 'height':240, 'current_idx':currIdx, 'title':_("Select audio track"), 'options':options})
        else:
            self.showMessage(_("Information about audio tracks not available."), MessageBox.TYPE_INFO, None)
            
    def selectAudioTrackCallback(self, ret):
        printDBG("selectAudioTrackCallback ret[%r]" % [ret])
        if isinstance(ret, IPTVChoiceBoxItem):
            ret = ret.privateData
            if 'track_id' in ret and ret['track_id'] != self.playback['AudioTrack'].get('id', -1):
                self.metaHandler.setAudioTrackIdx( ret.get('track_idx', -1) )
                self.extPlayerCmddDispatcher.setAudioTrack( ret['track_id'] )
            
    def selectSubtitle(self):
        printDBG("selectSubtitle")
        options = []
        
        currIdx = self.metaHandler.getSubtitleIdx()+1
        
        item = IPTVChoiceBoxItem(_('None'), "", {'other':'none'})
        if 0 == currIdx:
            item.type = IPTVChoiceBoxItem.TYPE_ON
        else:
            item.type = IPTVChoiceBoxItem.TYPE_OFF
        options.append( item )
        
        tracksTab = self.metaHandler.getSubtitlesTracks()
        for trackIdx in range(len(tracksTab)):
            name = '[{0}] {1}'.format(tracksTab[trackIdx]['lang'], tracksTab[trackIdx]['title'])
            item = IPTVChoiceBoxItem(name, "", {'track_idx':trackIdx})
            if (trackIdx + 1) == currIdx:
                item.type = IPTVChoiceBoxItem.TYPE_ON
            else:
                item.type = IPTVChoiceBoxItem.TYPE_OFF
            options.append( item )
        if self.subHandler['enabled'] and None != self.metaHandler.getSubtitleTrack():
            options.append( IPTVChoiceBoxItem(_('Synchronize'), "", {'other':'synchro'}) )
        if len(self.externalSubTracks):
            options.append( IPTVChoiceBoxItem(_('Download suggested'), "", {'other':'download_suggested'}) )
        options.append( IPTVChoiceBoxItem(_('Load'), "", {'other':'load'}) )
        options.append( IPTVChoiceBoxItem(_('Download'), "", {'other':'download'}) )
        self.openChild(boundFunction(self.childClosed, self.selectSubtitleCallback), IPTVChoiceBoxWidget, {'width':600, 'current_idx':currIdx, 'title':_("Select subtitles track"), 'options':options})
    
    def selectSubtitleCallback(self, ret):
        printDBG("selectSubtitleCallback ret[%r]" % [ret])
        if isinstance(ret, IPTVChoiceBoxItem):
            ret = ret.privateData
            if 'other' in ret:
                option = ret['other']
                if option == 'none':
                    self.metaHandler.setSubtitleIdx(-1)
                    self.disableSubtitles()
                elif option == 'synchro':
                    self.showSubSynchroControl()
                elif option == 'load':
                    self.openSubtitlesFromFile()
                elif option == 'download':
                    self.downloadSub()
                elif option == 'download_suggested':
                    self.downloadSub(True)
            elif 'track_idx' in ret:
                self.metaHandler.setSubtitleIdx( ret['track_idx'] )
                self.enableSubtitles()
    
    def openSubtitlesFromFile(self):
        printDBG("openSubtitlesFromFile")
        currDir = GetSubtitlesDir()
        
        fileSRC = self.fileSRC
        tmpMatch = 'file://'
        if fileSRC.startswith(tmpMatch): 
            fileSRC = fileSRC[len(tmpMatch):].replace('//', '/')
        if fileExists(fileSRC) and not fileSRC.endswith('/.iptv_buffering.flv'):
            try: currDir, tail = os_path.split(fileSRC)
            except: printExc()
        fileMatch = re.compile("^.*?(:?\.mlp|\.srt)$")
        self.openChild(boundFunction(self.childClosed, self.openSubtitlesFromFileCallback), IPTVFileSelectorWidget, currDir, _("Select subtitles file"), fileMatch)
        
    def openSubtitlesFromFileCallback(self, filePath=None):
        printDBG("openSubtitlesFromFileCallback filePath[%s]" % filePath)
        if None != filePath:
            self.subHandler['handler'].removeCacheFile(filePath)
            cmd = '%s "%s"' % (config.plugins.iptvplayer.uchardetpath.value, filePath) 
            self.workconsole = iptv_system(cmd, boundFunction(self.enableSubtitlesFromFile, filePath))
        
    def enableSubtitlesFromFile(self, filePath, code=127, encoding=""):
        if 0 != code or 'unknown' in encoding:
            encoding = ''
        else:
            encoding = encoding.strip()
        
        # WORKAROUND for incorrectly recognized CP1250 encoding as iso-8859-2
        # because charset do not have model for CP1250 for polish language, 
        # it incorrectly recognizes such coding as iso-8859-2
        if GetDefaultLang() == 'pl' and encoding == 'iso-8859-2':
            encoding = GetPolishSubEncoding(filePath)
        elif '' == encoding:
            encoding = 'utf-8'
        
        printDBG("enableSubtitlesFromFile filePath[%s] encoding[%s]" % (filePath, encoding))
        if None != filePath:
            lang = CParsingHelper.getSearchGroups(filePath, "_([a-z]{2})_[0-9]+?_[0-9]+?_[0-9]+?(:?\.mlp|\.srt)$")[0]
            try: currDir, fileName = os_path.split(filePath)
            except: 
                printExc()
                return
            trackIdx = -1
            tracks = self.metaHandler.getSubtitlesTracks()
            for idx in range(len(tracks)):
                try:
                    if os_path.samefile(tracks[idx]['path'], filePath):
                        trackIdx = idx
                        break
                except: printExc()
            if -1 == trackIdx:
                trackIdx = self.metaHandler.addSubtitleTrack( {"title":fileName, "id":"", "provider":"", "lang":lang, "delay_ms":0, "path":filePath} )
            self.metaHandler.setSubtitleIdx( trackIdx )
            self.enableSubtitles(encoding)

    def disableSubtitles(self):
        self.hideSubtitles()
        self.subHandler['enabled'] = False
        self.updateSubSynchroControl()
        
    def enableSubtitles(self, encoding='utf-8'):
        printDBG("enableSubtitles")
        if self.isClosing: return
        track = self.metaHandler.getSubtitleTrack()
        if None == track:
            if not self.metaHandler.hasSubtitlesTracks() and self.subConfig['auto_enable']:
                fileSRC = self.fileSRC
                tmpMatch = 'file://'
                if fileSRC.startswith(tmpMatch): 
                    fileSRC = fileSRC[len(tmpMatch):].replace('//', '/')
                if fileExists(fileSRC) and not fileSRC.endswith('/.iptv_buffering.flv'):
                    subFile = ''
                    try:
                        name, ext = os_path.splitext(fileSRC)
                        for ext in ['.srt', '.mlp']:
                            if fileExists(name + ext):
                                subFile = name + ext
                                break
                    except:
                        printExc()
                    if '' != subFile:
                        self.openSubtitlesFromFileCallback(subFile)
            return
        
        printDBG("enableSubtitles track[%s]" % track)
        
        path = track['path']
        sts = self.subHandler['handler'].loadSubtitles(path, encoding)
        if not sts:
            # we will remove this subtitles track as it is can not be used
            self.metaHandler.removeSubtitleTrack(self.metaHandler.getSubtitleIdx())
            msg = _("An error occurred while loading a subtitle from [%s].") % path
            self.showMessage(msg, MessageBox.TYPE_ERROR)
            return
        self.subHandler['marker']  = None
        self.subHandler['enabled'] = True
        self.updateSubSynchroControl()
        
    def updatSubtitlesTime(self):
        if -1 != self.subHandler['last_time'] and -1 != self.subHandler['latach_time']:
            timeMS = self.subHandler['last_time'] + int((time.time() - self.subHandler['latach_time']) * 1000)
            self.subHandler['current_sub_time_ms'] = timeMS
            self.updateSubtitles(timeMS)
        
    def latchSubtitlesTime(self, timeMS):
        self.subHandler['latach_time'] = time.time()
        self.subHandler['last_time']   = timeMS
        self.updateSubtitles(timeMS)
    
    def updateSubtitles(self, timeMS, force = False):
        if self.isClosing: return
        if not self.subHandler['enabled']: return
        if None == self.metaHandler.getSubtitleTrack(): return
        
        # marker is used for optimization 
        # we remember some kind of fingerprint for last subtitles 
        # subtitles handler first check this fingerprint 
        # if the previous one is the same as current and it will return None instead 
        # of subtitles text
        prevMarker = self.subHandler['marker']
        if force: prevMarker = None
        
        delay_ms = self.metaHandler.getSubtitleTrackDelay()
        marker, text = self.subHandler['handler'].getSubtitles(timeMS + delay_ms, prevMarker)
        if None != text:
            self.subHandler['marker'] = marker
            #printDBG("===============================================================")
            #printDBG(text)
            #printDBG("===============================================================")
            if "" == text:
                self.hideSubtitles()
            else:
                self.setSubtitlesText(text)
                
    def hideSubtitles(self):
        for idx in range(self.subLinesNum):
            self['subLabel%d'%(idx+1)].hide()
    
    def setSubtitlesText(self, text, stripLine = True):
        back = True
        desktopW = getDesktop(0).size().width()
        desktopH = getDesktop(0).size().height()
        
        dW = desktopW - 20
        dH = self.subConfig['box_height']
        
        if self.subLinesNum == 1 and 'transparent' == self.subConfig['background']:
            self['subLabel1'].setText(text)
            self['subLabel1'].show()
        else:
            if self.subLinesNum == 1:
                lineHeight = self.subConfig['line_height'] * text.count('\n')
                text = [text]
            else:
                text = text.split('\n')
                text.reverse()
                lineHeight = self.subConfig['line_height']
            y = self.subConfig['pos']
            for lnIdx in range(self.subLinesNum):
                subLabel = 'subLabel%d' % (lnIdx+1)
                if lnIdx < len(text):
                    lnText = text[lnIdx]
                    if stripLine:
                        lnText = lnText.strip()
                else:
                    lnText = ''

                if '' == lnText:
                    self[subLabel].hide()
                    continue
                try:
                    self[subLabel].instance.resize(eSize(dW, dH))
                    self[subLabel].resize(eSize(dW, dH))
                    
                    self[subLabel].setText(lnText)
                    textSize = self[subLabel].getSize()
                    lW = textSize[0] + self.subConfig['font_size'] / 2
                    lH = lineHeight #textSize[1] + self.subConfig['font_size'] / 2
                    self[subLabel].instance.resize(eSize(lW, lH))
                    self[subLabel].instance.move( ePoint((desktopW-lW) / 2, desktopH - y - lH) )
                    y += lH + self.subConfig['line_spacing']
                    self[subLabel].show()
                except:
                    printExc()
        
    def updateInfo(self):
        self.extPlayerCmddDispatcher.doUpdateInfo()
        if None != self.downloader:
            remoteFileSize = self.downloader.getRemoteFileSize()
            if 0 < remoteFileSize:
                localFileSize = self.downloader.getLocalFileSize(True) 
                if 0 < localFileSize:
                    self['bufferingBar'].value = (localFileSize * 100000) / remoteFileSize
                    
    def showMessage(self, message, type, callback=None):
        printDBG("IPTVExtMoviePlayer.showMessage")
        if self.isClosing and type != None: return
        messageItem = {'msg':message, 'type':type, 'callback':callback}
        self.messageQueue.append(messageItem)
        self.processMessageQueue()
        
    def processMessageQueue(self):
        if self.underMessage or 0 == len(self.messageQueue): return
        self.underMessage = True
        while len(self.messageQueue):
            messageItem = self.messageQueue.pop(0)
            message, type, callback = messageItem['msg'], messageItem['type'], messageItem['callback']
            if None == type and None != callback: 
                callback()
            else:
                if self.isClosing and None != callback: continue # skip message with callback
                else: self.session.openWithCallback(boundFunction(self.messageClosedCallback, callback), MessageBox, text=message, type=type)
            return
        
    def messageClosedCallback(self, callback, arg=None):
        self.underMessage = False
        if None != callback: callback()
        else: self.processMessageQueue()
            
    def waitEOSAbortedFixTimeoutCallback(self):
        if self.waitEOSAbortedFix['EOSaborted_received']:
            self.extPlayerCmddDispatcher.stop()
        
    def playbackUpdateInfo(self, stsObj):
        for key, val in stsObj.iteritems():
            if 'Length' == key: 
                if 0 > val:
                    printDBG('IPTVExtMoviePlayer.playbackUpdateInfo Length[%d] - live stream?' % val )
                    val = 0
                    self.playback['IsLive'] = True
                else:
                    self.playback['IsLive'] = False
                if 0 < val:
                    # restore last position
                    if 10 < self.lastPosition and self.lastPosition < (self.playback['Length'] - 10):
                        self.showPlaybackInfoBar()
                        self.extPlayerCmddDispatcher.doGoToSeek(str(self.lastPosition-5))
                        self.lastPosition = 0
                    tmpLength = self.playback['CurrentTime']
                    if val > self.playback['CurrentTime']: tmpLength = val
                    if 0 < tmpLength:
                        self.playback['Length'] = tmpLength
                        self['progressBar'].range = (0, tmpLength)
                        self['lengthTimeLabel'].setText( str(timedelta(seconds=tmpLength)) )
                    self.playback['LengthFromPlayerReceived'] = True
            elif 'CurrentTime' == key:
                if self.playback['Length'] < val:
                    self.playback['Length'] = val
                    self['progressBar'].range = (0, val)
                    self['lengthTimeLabel'].setText( str(timedelta(seconds=val)) )
                self['progressBar'].value = val
                self.playback['CurrentTime'] = stsObj['CurrentTime']
                if 0 < self.playback['CurrentTime']: self.playback['StartGoToSeekTime'] = self.playback['CurrentTime']
                self['currTimeLabel'].setText( str(timedelta(seconds=self.playback['CurrentTime'])) )
                self['remainedLabel'].setText( '-' + str(timedelta(seconds=self.playback['Length']-self.playback['CurrentTime'])) )
            elif 'Status' == key:
                curSts = self.playback['Status']
                if self.playback['Status'] != val[0]:
                    if 'Play' == val[0]:
                        self.showPlaybackInfoBar()
                    elif val[0] in ['Pause', 'FastForward', 'SlowMotion']:
                        self.showPlaybackInfoBar(blocked=True)
                    self.playback['Status'] = val[0]
                    self['statusIcon'].setPixmap( self.playback['statusIcons'].get(val[0], None) )
            else:
                self.playback[key] = val
                printDBG(">>> playback[%s] = %s" % (key, val))
                
    def doGoToSeek(self):
        self.playback['GoToSeekTimer'].stop()
        if self.playback['GoToSeeking']:
            self.showPlaybackInfoBar()
            self.playback['StartGoToSeekTime'] = self.playback['GoToSeekTime']
            self.extPlayerCmddDispatcher.doGoToSeek(str(self.playback['GoToSeekTime']))
            self.playback['GoToSeeking'] = False
            self['goToSeekPointer'].hide()
            self["goToSeekLabel"].hide()

    def doGoToSeekPointerMove(self, seek):
        printDBG('IPTVExtMoviePlayer.doGoToSeekPointerMove seek[%r], LengthFromPlayerReceived[%r], GoToSeeking[%r]' % (seek, self.playback['LengthFromPlayerReceived'], self.playback['GoToSeeking']))
        self.playback['GoToSeekTimer'].stop()
        if not self.playback['LengthFromPlayerReceived']: return
        if not self.playback['GoToSeeking']:
            self.playback['GoToSeeking']  = True
            self.playback['GoToSeekTime'] = self.playback['StartGoToSeekTime']
            self.showPlaybackInfoBar([], True)
            self['goToSeekPointer'].show()
            self["goToSeekLabel"].show()
        
        # update data
        self.playback['GoToSeekTime'] += seek
        if self.playback['GoToSeekTime'] < 0: self.playback['GoToSeekTime'] = 0
        if self.playback['GoToSeekTime'] > self.playback['Length']: self.playback['GoToSeekTime'] = self.playback['Length']
        self["goToSeekLabel"].setText( str(timedelta(seconds=self.playback['GoToSeekTime'])) )
        
        # update position
        # convert time to width
        relativeX = self["progressBar"].instance.size().width() * self.playback['GoToSeekTime'] / self.playback['Length']
        x = self['progressBar'].position[0] - self["goToSeekPointer"].getWidth()/2 + relativeX

        self['goToSeekPointer'].setPosition(x, self['goToSeekPointer'].position[1])
        self["goToSeekLabel"].setPosition(x, self['goToSeekLabel'].position[1])
        
        # trigger delayed seek
        self.playback['GoToSeekTimer'].start(1000)
        
    def saveLastPlaybackTime(self):
        lastPosition = self.playback.get('CurrentTime', 0)
        if config.plugins.iptvplayer.remember_last_position.value and lastPosition > 0:
            self.metaHandler.setLastPosition( lastPosition )
            
    def loadLastPlaybackTime(self):
        if config.plugins.iptvplayer.remember_last_position.value and self.lastPosition < 1:
            self.lastPosition = self.metaHandler.getLastPosition()
    
    # handling of RCU keys
    def key_stop(self):
        self.isCloseRequestedByUser = True
        self.extPlayerCmddDispatcher.stop()
        self.saveLastPlaybackTime()
    def key_play(self):         self.extPlayerCmddDispatcher.play()
    def key_pause(self):        self.extPlayerCmddDispatcher.pause()
    def key_exit(self):         self.doExit()
    def key_info(self):         self.doInfo()
    def key_seek1(self):        self.extPlayerCmddDispatcher.doSeek(config.seek.selfdefined_13.value * -1)
    def key_seek3(self):        self.extPlayerCmddDispatcher.doSeek(config.seek.selfdefined_13.value) 
    def key_seek4(self):        self.extPlayerCmddDispatcher.doSeek(config.seek.selfdefined_46.value * -1)
    def key_seek6(self):        self.extPlayerCmddDispatcher.doSeek(config.seek.selfdefined_46.value)
    def key_seek7(self):        self.extPlayerCmddDispatcher.doSeek(config.seek.selfdefined_79.value * -1)
    def key_seek9(self):        self.extPlayerCmddDispatcher.doSeek(config.seek.selfdefined_79.value)  
    def key_seekFwd(self):      self.extPlayerCmddDispatcher.seekFwd()   
    def key_seekBack(self):     self.extPlayerCmddDispatcher.seekBack()   
    def key_left_press(self):   self.goToSeekKey(-1, 'press')
    def key_left_repeat(self):  self.goToSeekKey(-1, 'repeat')
    def key_rigth_press(self):  self.goToSeekKey(1, 'press')
    def key_rigth_repeat(self): self.goToSeekKey(1, 'repeat')
    def key_up_press(self):     self.goSubSynchroKey(-1, 'press')
    def key_up_repeat(self):    self.goSubSynchroKey(-1, 'repeat') 
    def key_down_press(self):   self.goSubSynchroKey(1, 'press')
    def key_down_repeat(self):  self.goSubSynchroKey(1, 'repeat')
    
    def key_ok(self):
        if 'Pause' == self.playback['Status']: self.extPlayerCmddDispatcher.play()
        else: self.extPlayerCmddDispatcher.pause()
    
    def key_subtitles(self):
        self.selectSubtitle()
    
    def key_audio(self):
        self.selectAudioTrack()
    
    def key_videooption(self):
        self.selectVideoOptions()
        
    def key_menu(self):
        self.showMenuOptions()
        
    def goSubSynchroKey(self, direction, state='press'):
        if not self.subHandler['synchro']['visible'] or not self.subHandler['enabled'] or None == self.metaHandler.getSubtitleTrack():
            self.hideSubSynchroControl()
            return
        currentDelay = self.metaHandler.getSubtitleTrackDelay()
        currentDelay += direction * 500 # in MS
        self.metaHandler.setSubtitleTrackDelay(currentDelay)
        self.updateSubSynchroControl()
        
    def updateSubSynchroControl(self):
        if not self.subHandler['synchro']['visible'] or not self.subHandler['enabled'] or None == self.metaHandler.getSubtitleTrack():
            self.hideSubSynchroControl()
            return
        currentDelay = self.metaHandler.getSubtitleTrackDelay()
        if currentDelay > 0:
            textDelay = '+'
        else: textDelay = '' 
        textDelay += "%.1fs" % (currentDelay / 1000.0)
        self['subSynchroLabel'].setText(textDelay)
        if -1 != self.subHandler['current_sub_time_ms']:
            self.updateSubtitles(self.subHandler['current_sub_time_ms'])
        
    def goToSeekKey(self, direction, state='press'):
        if 'press' == state: 
            self.goToSeekStep = 5
            self.goToSeekRepeatCount = 1
        elif 3 <= self.goToSeekRepeatCount:
            self.goToSeekRepeatCount = 1
            self.goToSeekStep *= 2
        else:
            self.goToSeekRepeatCount += 1
        
        # not allow faster than (0.1 * playback length)
        if self.goToSeekStep > (self.playback['Length'] / 10):
            self.goToSeekStep = self.playback['Length'] / 10
        if 0 >= self.goToSeekStep:
            self.goToSeekStep = 1
        
        self.doGoToSeekPointerMove(self.goToSeekStep * direction)
        
    def doExit(self, fromInfo=False):
        if not fromInfo and self.subHandler['synchro']['visible']:
            self.hideSubSynchroControl()
        elif self.playbackInfoBar['visible']:
            self.playbackInfoBar['blocked'] = False
            self.hidePlaybackInfoBar()
        elif not self.isClosing:
            self.extPlayerCmddDispatcher.stop()
            self.saveLastPlaybackTime()
            
    def doInfo(self):
        if not self.playbackInfoBar['visible']:
            if self.isStarted and not self.isClosing:
                self.playbackInfoBar['blocked'] = True
                self.showPlaybackInfoBar()
        else: self.doExit(True)
    
    def eplayer3Finished(self, code):
        printDBG("IPTVExtMoviePlayer.eplayer3Finished code[%r]" % code)
        if self.isClosing: return
         
        msg = _("It seems that the video player \"%s\" does not work properly.\n\nSTS: %s\nERROR CODE: %r")
        if None == self.playerBinaryInfo['version']:
            msg = msg % (self.playerName, self.playerBinaryInfo['data'], code)
            self.showMessage(msg, MessageBox.TYPE_ERROR, self.onLeavePlayer)
        elif 'gstplayer' == self.player and 246 == code:
            msg = msg % (self.playerName, _("ERROR: pipeline could not be constructed: no element \"playbin2\" \nPlease check if gstreamer plugins are available in your system."), code)
            self.showMessage(msg, MessageBox.TYPE_ERROR, self.onLeavePlayer)
        else: self.onLeavePlayer()
        
    def waitCloseTimeoutCallback(self):
        printDBG("IPTVExtMoviePlayer.waitCloseTimeoutCallback")
        if None != self.console:
            printDBG("Force close movie player by sending CtrlC")
            self.console.sendCtrlC()
        self.onLeavePlayer()
        
    def eplayer3DataAvailable2(self, data):
        if None == data or self.isClosing:
            return
            
        if 'got buffer empty from driver!' in data:
            self.extPlayerCmddDispatcher.stop()

        # work around to catch EOF event after seeking, pause .etc
        if 'wait EOS aborted!!' in data:
            self.waitEOSAbortedFix['EOSaborted_received'] = True
            self.waitEOSAbortedFix['timer'].start(2000, True) # singleshot

        if self.waitEOSAbortedFix['EOSaborted_received'] and 'poll' in data:
            self.waitEOSAbortedFix['timer'].stop()
            self.waitEOSAbortedFix['timer'].start(2000, True)

    def eplayer3DataAvailable(self, data):
        
        def _mapTrack(obj, video=False):
            printDBG('>>>> _mapTrack [%s]' % obj)
            params = {}
            params['id']         = int(obj['id'])
            params['encode']     = str(obj['e'][2:])
            params['name']       = str(obj['n'])
            if video:
                params['frame_rate'] = float(obj['f']/1000)
                params['width']      = int(obj['w'])
                params['height']     = int(obj['h'])
            return params
        
        if None == data or self.isClosing:
            return
        if None == self.playerBinaryInfo['version']: self.playerBinaryInfo['data'] += data
        data = self.responseData + data
        if '\n' != data[-1]: truncated = True
        else:                truncated = False
        data = data.split('\n')
        if truncated: 
            self.responseData = data[-1]
            del data[-1]
        for item in data:
            #printDBG(item)
            if item.startswith('{'): 
                try:
                    obj = json.loads(item.strip())
                    #printDBG("Status object [%r]" % obj)
                    key = obj.keys()[0]
                    obj = obj[key]
                except: 
                    printExc()
                    continue
                    
                if "T" == key: #ADD_TRIGGERS
                    self.latchSubtitlesTime(obj['c'])
                elif "PLAYBACK_PLAY" == key:
                    self.onStartPlayer()
                    #if 'gstplayer' != self.player: 
                    self.updateInfoTimer.start(1000)
                elif "PLAYBACK_STOP" == key:
                    self.onLeavePlayer()
                elif "PLAYBACK_LENGTH" == key and 0 == obj['sts']:
                    self.playbackUpdateInfo({'Length':int(obj['length'])})
                elif "PLAYBACK_CURRENT_TIME" == key and 0 == obj['sts']:
                    self.playbackUpdateInfo({'CurrentTime':int(obj['sec'])})
                elif "J" == key and obj['ms'] > 0:
                    self.playbackUpdateInfo({'CurrentTime':int(obj['ms']/1000)})
                    self.latchSubtitlesTime(obj['ms'])
                # CURRENT VIDEO TRACK
                elif "v_c" == key:
                    self.playbackUpdateInfo({'VideoTrack':_mapTrack(obj, True)})
                elif "a_c" == key:
                    self.playbackUpdateInfo({'AudioTrack':_mapTrack(obj)})
                elif "a_l" == key:
                    tracks = []
                    for item in obj:
                        tracks.append( _mapTrack(item) )
                    self.playbackUpdateInfo({'AudioTracks':tracks})
                elif "PLAYBACK_INFO" == key:
                    if obj['isPaused']:
                        self.playbackUpdateInfo({'Status': ['Pause', '0']})
                        #if 'gstplayer' == self.player: self.updateInfoTimer.stop()
                        self.subHandler['timer'].stop()
                    else:
                        #if 'gstplayer' == self.player: self.updateInfoTimer.start(1000)
                        if self.subHandler['enabled']: self.subHandler['timer'].start(100)
                        if obj['isForwarding']:
                            self.playbackUpdateInfo({'Status': ['FastForward', str(obj['Speed'])]})
                        elif 0 < obj['SlowMotion']:
                            self.playbackUpdateInfo({'Status': ['SlowMotion', '1/%d' % obj['SlowMotion']]})
                        elif obj['isPlaying']: # and 1 == obj['Speed']:
                            self.playbackUpdateInfo({'Status': ['Play', '1']})
                        else:
                            printDBG('eplayer3DataAvailable PLAYBACK_INFO not handled')
                elif "GSTPLAYER_EXTENDED" == key: self.playerBinaryInfo['version'] = obj['version']
                elif "EPLAYER3_EXTENDED" == key: self.playerBinaryInfo['version'] = obj['version']
                elif "GST_ERROR" == key: self.showMessage('%s\ncode:%s' % (obj['msg'].encode('utf-8'), obj['code']), MessageBox.TYPE_ERROR, None)
                elif "GST_MISSING_PLUGIN" == key: self.showMessage(obj['msg'].encode('utf-8'), MessageBox.TYPE_INFO, None)

                        
                # {u'PLAYBACK_INFO': 
                # {u'isSeeking': False, 
                # u'BackWard': 0.0, 
                # u'isForwarding': False, 
                # u'mayWriteToFramebuffer': True, 
                # u'AVSync': 1, 
                # u'isTeletext': False, 
                # u'isAudio': True, 
                # u'isCreationPhase': False, 
                # u'abortRequested': False, 
                # u'isVideo': True, 
                # u'isPaused': False, 
                # u'SlowMotion': 0, 
                # u'isPlaying': True, 
                # u'Speed': 1, 
                # u'isSubtitle': False, 
                # u'isDvbSubtitle': False}}
                
    def onDownloadFinished(self, sts):
        printDBG("IPTVExtMoviePlayer.onDownloadFinished sts[%s]" % sts)
        if None != self.extPlayerCmddDispatcher:
            self.extPlayerCmddDispatcher.setDownloadFileTimeout(0)

    def __onClose(self):
        self.isClosing = True
        if None != self.workconsole:
            self.workconsole.kill()
        self.workconsole = None
        if None != self.console:
            self.console_appClosed_conn   = None
            self.console_stderrAvail_conn = None
            self.console_stdoutAvail_conn = None
            self.console.sendCtrlC()
            self.console = None
        if None != self.downloader:
            self.downloader.unsubscribeFor_Finish(self.onDownloadFinished)
        self.downloader = None
        self.playbackInfoBar['timer'].stop()
        self.playbackInfoBar['timer_conn'] = None
        self.waitEOSAbortedFix['timer_conn'] = None
        self.waitCloseFix['timer_conn'] = None
        
        self.subHandler['timer'].stop()
        self.subHandler['timer_conn'] = None
        
        self.updateInfoTimer_conn = None
        self.playback['GoToSeekTimer_conn'] = None
        self.onClose.remove(self.__onClose)
        self.messageQueue = []
        
        # RESTORE DEFAULT VIDEO OPTION
        printDBG(">>>>>>>>>>>>>>>>>>>>> __onClose[%s]" % self.defVideoOptions)
        printDBG(">>>>>>>>>>>>>>>>>>>>> __onClose[%s]" % self.currVideoOptions)
        videoOptionChange = False
        for opt in ['aspect', 'policy', 'policy2']:
            val  = self.defVideoOptions[opt] 
            val2 = self.currVideoOptions[opt]
            if val in self.defVideoOptions['%s_choices' % opt] and val != val2:
                videoOptionChange = True
                break
                
        if videoOptionChange:
            self.applyVideoOptions(self.defVideoOptions)
            
        # RESTORE DEFAULT AUDIO OPTION
        playerDefOptions = self.getE2AudioOptions()
        audioOptions = ['ac3', 'aac']
        for opt in audioOptions:
            if playerDefOptions[opt] != None and playerDefOptions[opt] != self.defAudioOptions[opt]:
                SetE2AudioCodecMixOption(opt, self.defAudioOptions[opt])
        
        self.metaHandler.save()
        
    def onStartPlayer(self):
        self.isStarted = True
        self.showPlaybackInfoBar()

    def onLeavePlayer(self):
        printDBG("IPTVExtMoviePlayer.onLeavePlayer")
        if self.waitCloseFix['waiting'] and None != self.waitCloseFix['timer']: self.waitCloseFix['timer'].stop()
        self.updateInfoTimer.stop()
        self.subHandler['timer'].stop()
        self.playbackInfoBar['blocked'] = False
        self.hidePlaybackInfoBar()
        
        # onLeavePlayer can be called by two reason:
        #   - no data in buffer - should return sts = 1
        #   - triggered by user - should return sts = 0
        if self.isCloseRequestedByUser: 
            sts = 0
        else:
            sts = 1
            
        self.isClosing = True
        self.showMessage(None, None, boundFunction(self.extmovieplayerClose, sts, self.playback.get('CurrentTime', 0)))

    def extmovieplayerClose(self, sts, currentTime):
        if self.childWindowsCount > 0:
            self.delayedClosure = boundFunction(self.close, sts, currentTime)
        else:
            self.close(sts, currentTime)
            
    def openChild(self, *args):
        self.childWindowsCount += 1
        self.session.openWithCallback(*args)
    
    def childClosed(self, callback, *args):
        self.childWindowsCount -= 1
        callback(*args)
        
        if None != self.delayedClosure and self.childWindowsCount < 1:
            self.delayedClosure()
            
    def downloadSub(self, simple=False):
        if not simple:
            self.openChild(boundFunction(self.childClosed, self.downloadSubCallback), IPTVSubDownloaderWidget, {'movie_title':self.title})
        else:
            self.openChild(boundFunction(self.childClosed, self.downloadSubCallback), IPTVSubSimpleDownloaderWidget, {'movie_title':self.title, 'sub_list':self.externalSubTracks})
        
    def downloadSubCallback(self, ret = None):
        if None != ret:
            self.subHandler['handler'].removeCacheFile(ret.get('path', ''))
            idx = self.metaHandler.addSubtitleTrack(ret)
            self.metaHandler.setSubtitleIdx( idx )
            self.enableSubtitles()
        
    def onStart(self):
        self.onShow.remove(self.onStart)
        #self.onLayoutFinish.remove(self.onStart)
        self['progressBar'].value = 0
        self['bufferingBar'].range = (0, 100000)
        self['bufferingBar'].value = 0
        self.initGuiComponentsPos()
        self.metaHandler.load()
        self.loadLastPlaybackTime()
        if 'gstplayer' == self.player:
            if None != self.downloader:
                self.downloader.subscribeFor_Finish(self.onDownloadFinished)
            
            gstplayerPath = config.plugins.iptvplayer.gstplayerpath.value
            #'export GST_DEBUG="*:6" &&' + 
            cmd = gstplayerPath  + ' "%s"' % self.fileSRC
            
            # active audio track 
            audioTrackIdx = self.metaHandler.getAudioTrackIdx()
            cmd += ' %d ' % audioTrackIdx
            
            # file download timeout
            if None != self.downloader and self.downloader.isDownloading():
                timeout = self.gstAdditionalParams['file-download-timeout']
            else: timeout = 0
            cmd += ' {0} '.format( timeout )
            
            # file download live
            if self.gstAdditionalParams['file-download-live']:
                cmd += ' {0} '.format(1)
            else: cmd += ' {0} '.format(0)
            
            if "://" in self.fileSRC: 
                cmd += ' "%s" "%s"  "%s"  "%s" ' % (self.gstAdditionalParams['download-buffer-path'], self.gstAdditionalParams['ring-buffer-max-size'], self.gstAdditionalParams['buffer-duration'], self.gstAdditionalParams['buffer-size'])
                tmp = strwithmeta(self.fileSRC)
                url,httpParams = DMHelper.getDownloaderParamFromUrlWithMeta(tmp)
                for key in httpParams: cmd += (' "%s=%s" ' % (key, httpParams[key]) )
                if 'http_proxy' in tmp.meta:
                    tmp = tmp.meta['http_proxy']
                    if '://' in tmp:
                        if '@' in tmp:
                            tmp = re.search('([^:]+?://)([^:]+?):([^@]+?)@(.+?)$', tmp)
                            if tmp: cmd += (' "proxy=%s" "proxy-id=%s" "proxy-pw=%s" ' % (tmp.group(1)+tmp.group(4), tmp.group(2), tmp.group(3)) )
                        else: cmd += (' "proxy=%s" ' % tmp)
            cmd += " > /dev/null"
        else:
            exteplayer3path = config.plugins.iptvplayer.exteplayer3path.value
            cmd = exteplayer3path
            if "://" in self.fileSRC: 
                url,httpParams = DMHelper.getDownloaderParamFromUrlWithMeta( strwithmeta(self.fileSRC) )
                #cmd += ' ""' # cookies for now will be send in headers
                headers = ''
                for key in httpParams:
                    if key == 'User-Agent':
                        cmd += ' -u "%s"' %  httpParams[key]
                    headers += ('%s: %s\r\n' % (key, httpParams[key]) )
                if len(headers):
                    cmd += ' -h "%s"' % headers
            if config.plugins.iptvplayer.aac_software_decode.value:
                cmd += ' -a -p 10'
            elif config.plugins.iptvplayer.plarform.value in ('mipsel', 'armv7'):
                cmd += ' -p 2'
            audioTrackIdx = self.metaHandler.getAudioTrackIdx()
            printDBG(">>>>>>>>>>>>>>>>>>>>>>>> audioTrackIdx[%d]" % audioTrackIdx)
            if audioTrackIdx >= 0:
                cmd += ' -t %d ' % audioTrackIdx
            cmd += (' "%s"' % self.fileSRC) + " > /dev/null"
        
        self.console = eConsoleAppContainer()
        self.console_appClosed_conn = eConnectCallback(self.console.appClosed, self.eplayer3Finished)
        self.console_stderrAvail_conn = eConnectCallback(self.console.stderrAvail, self.eplayer3DataAvailable)
        #if 'gstplayer' == self.player: 
        #    self.console_stdoutAvail_conn = eConnectCallback(self.console.stdoutAvail, self.eplayer3DataAvailable2 ) # work around to catch EOF event after seeking, pause .etc
        printDBG("->||||||| onStart cmd[%s]" % cmd)
        self.console.execute( E2PrioFix( cmd ) )
        self['statusIcon'].setPixmap( self.playback['statusIcons']['Play'] ) # sulge for test
        self['logoIcon'].setPixmap( self.playback['logoIcon'] )
        self['subSynchroIcon'].setPixmap( self.subHandler['synchro']['icon'] )
        
        # SET Video option
        videoOptions = ['aspect', 'policy', 'policy2']
        playerDefOptions = self.configObj.getDefaultPlayerVideoOptions()
        for opt in videoOptions:
            val = self.metaHandler.getVideoOption(opt)
            if val != None:
                self.currVideoOptions[opt] = val
            elif playerDefOptions[opt] != None:
                self.currVideoOptions[opt] = playerDefOptions[opt]
        
        videoOptionChange = False
        self.defVideoOptions = self.getE2VideoOptions()
        for opt in videoOptions:
            val = self.currVideoOptions[opt]
            if val in self.defVideoOptions['%s_choices' % opt] and val != self.defVideoOptions[opt]:
                videoOptionChange = True
                self.currVideoOptions[opt] = val
            else:
                self.currVideoOptions[opt] = self.defVideoOptions[opt]
        
        if videoOptionChange:
            self.applyVideoOptions(self.currVideoOptions)
            
        # SET Audio option
        self.defAudioOptions = self.getE2AudioOptions()
        playerDefOptions = self.configObj.getDefaultAudioOptions()
        audioOptions = ['ac3', 'aac']
        for opt in audioOptions:
            if playerDefOptions[opt] != None and playerDefOptions[opt] != self.defAudioOptions[opt]:
                SetE2AudioCodecMixOption(opt, playerDefOptions[opt])
        
        self.enableSubtitles()
            
    def initGuiComponentsPos(self):
        # info bar gui elements
        # calculate offset
        offset_x = (getDesktop(0).size().width() - self['playbackInfoBaner'].instance.size().width()) / 2
        offset_y = (getDesktop(0).size().height() - self['playbackInfoBaner'].instance.size().height()) - 50 # 10px - cropping guard
        if offset_x < 0: offset_x = 0
        if offset_y < 0: offset_y = 0

        for elem in self.playbackInfoBar['guiElemNames']:
            self[elem].setPosition(self[elem].position[0]+offset_x, self[elem].position[1]+offset_y)
            
        # sub synchro elements
        # calculate offset
        offset_x = (getDesktop(0).size().width() - self['subSynchroIcon'].instance.size().width()) / 2
        offset_y = (getDesktop(0).size().height() - self['subSynchroIcon'].instance.size().height()) / 2
        if offset_x < 0: offset_x = 0
        if offset_y < 0: offset_y = 0

        for elem in self.subHandler['synchro']['guiElemNames']:
            self[elem].setPosition(self[elem].position[0]+offset_x, self[elem].position[1]+offset_y)

    def showPlaybackInfoBar(self, excludeElems=['goToSeekPointer', 'goToSeekLabel'], blocked=None):
        self.playbackInfoBar['timer'].stop()
        
        for elem in self.playbackInfoBar['guiElemNames']:
            if elem not in excludeElems:
                self[elem].show()
        
        if None == blocked or self.playbackInfoBar['blocked']:
            blocked = self.playbackInfoBar['blocked']

        self.playbackInfoBar['visible'] = True

        if not blocked:
            self.playbackInfoBar['timer'].start(self.autoHideTime, True) # singleshot

    def hidePlaybackInfoBar(self, excludeElems=[], force=False):
        self.playbackInfoBar['timer'].stop()

        if self.playbackInfoBar['blocked'] and not force:
            return

        for elem in self.playbackInfoBar['guiElemNames']:
            if elem not in excludeElems:
                self[elem].hide()
            
        self.playbackInfoBar['visible'] = False
        
    def _showHideSubSynchroControl(self, show=True):
        for elem in self.subHandler['synchro']['guiElemNames']:
            if show:
                self[elem].show()
            else:
                self[elem].hide()
        self.subHandler['synchro']['visible'] = show
        
    def showSubSynchroControl(self):
        self._showHideSubSynchroControl(True)
        self.updateSubSynchroControl()

    def hideSubSynchroControl(self, excludeElems=[], force=False):
        self._showHideSubSynchroControl(False)
        
    def __onShow(self):
        pass
        #Screen.hide(self) # we do not need window at now maybe in future
        
    def fatalErrorHandler(self, msg):
        if self.fatalErrorOccurs: return
        self.fatalErrorOccurs = True
        self.showMessage(msg, MessageBox.TYPE_ERROR, self._fatalErrorCallback)
        
    def _fatalErrorCallback(self):
        self.waitCloseTimeoutCallback()
        
    def consoleWrite(self, data):
        try:
            self.console.write( data, len(data) )
            return
        except:
            try: 
                self.console.write( data )
                return
            except:
                printExc()
        msg = _("Fatal error: consoleWrite failed!")
        self.fatalErrorHandler(msg)
    
    def extPlayerSendCommand(self, command, arg1=''):
        #printDBG("IPTVExtMoviePlayer.extPlayerSendCommand command[%s] arg1[%s]" % (command, arg1))
        if None == self.console: 
            printExc("IPTVExtMoviePlayer.extPlayerSendCommand console not available")
            return
        if 'ADD_TRIGGERS' == command:
            self.consoleWrite( "t{0}\n".format(arg1) )
        elif   'PLAYBACK_LENGTH'       == command: 
            self.consoleWrite( "l\n" )
        elif 'PLAYBACK_CURRENT_TIME' == command: 
            self.consoleWrite( "j\n" )
        elif 'PLAYBACK_INFO'         == command: 
            self.consoleWrite( "i\n" )
        elif 'PLAYBACK_SET_AUDIO_TRACK' == command:
            self.consoleWrite( "a%s\n" % arg1)
            self.consoleWrite( "ac\n")
        elif 'PLAYBACK_SET_DOWNLOAD_FILE_TIMEOUT' == command:
            self.consoleWrite( "t%s\n" % arg1)
        else:
            # All below commands require that 'PLAY ' status, 
            # so we first send command to resume playback
            self.consoleWrite( "c\n" )
            
            if 'PLAYBACK_PAUSE'           == command: 
                self.consoleWrite( "p\n" )
            elif 'PLAYBACK_SEEK_RELATIVE' == command: 
                self.consoleWrite( "kc%s\n" % (arg1) ) 
            elif 'PLAYBACK_SEEK_ABS'      == command: 
                self.consoleWrite( "gf%s\n" % (arg1) )
            elif 'PLAYBACK_FASTFORWARD'   == command:
                self.consoleWrite( "f%s\n" % arg1 )
            elif 'PLAYBACK_FASTBACKWARD'  == command: 
                self.consoleWrite( "b%s\n" % arg1 )
            elif 'PLAYBACK_SLOWMOTION'    == command: 
                self.consoleWrite( "m%s\n" % arg1 )
            elif 'PLAYBACK_STOP'          == command: 
                if not self.waitCloseFix['waiting']:
                    self.waitCloseFix['waiting'] = True
                    self.waitCloseFix['timer'].start(5000, True) # singleshot
                self.consoleWrite( "q\n" )
            else:
                printDBG("IPTVExtMoviePlayer.extPlayerSendCommand unknown command[%s]" % command)
