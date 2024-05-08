import os

import wx

import addonHandler
import globalPluginHandler
import globalVars
import gui
from scriptHandler import script
import speech
from synthDriverHandler import getSynth
import ui

from .speechSettingsDialog import WorldVoiceSettingsDialog
from generics.speechSymbols.views import SpeechSymbolsDialog

from synthDrivers.WorldVoice import WVStart, WVEnd
from synthDrivers.WorldVoice.hook import Hook
from synthDrivers.WorldVoice.sayAll import patch, unpatch
from synthDrivers.WorldVoice.voiceManager import AisoundVoice

addonHandler.initTranslation()
ADDON_SUMMARY = addonHandler.getCodeAddon().manifest["summary"]
workspace_path = os.path.join(globalVars.appArgs.configPath, "WorldVoice-workspace")


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super().__init__()

		if globalVars.appArgs.secure:
			return

		self.createMenu()

		self.hookInstance = Hook()

		WVStart.register(self.hookInstance.start)
		WVEnd.register(self.hookInstance.end)
		WVStart.register(patch)
		WVEnd.register(unpatch)
		if getSynth().name == "WorldVoice":
			WVStart.notify()

	def terminate(self):
		try:
			self.removeMenu()
		except wx.PyDeadObjectError:
			pass

		if getSynth().name == "WorldVoice":
			WVEnd.notify()
		WVStart.unregister(self.hookInstance.start)
		WVEnd.unregister(self.hookInstance.end)
		WVStart.unregister(patch)
		WVEnd.unregister(unpatch)

	def createMenu(self):
		self.submenu_vocalizer = wx.Menu()

		item = self.submenu_vocalizer.Append(wx.ID_ANY, _("&Speech Settings"), _("Speech Settings."))
		gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.popup_SpeechSettingsDialog, item)
		item = self.submenu_vocalizer.Append(wx.ID_ANY, _("&Unicode Settings"), _("Unicode Settings."))
		gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.popup_SpeechSymbolsDialog, item)
		item = self.submenu_vocalizer.Append(wx.ID_ANY, _("&File Import"), _("Import File."))
		gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.onFileImport, item)
		if not AisoundVoice.install():
			item = self.submenu_vocalizer.Append(wx.ID_ANY, _("&Aisound Core Install"), _("Install Aisound Core."))
			gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.onAisoundCoreInstall, item)

		self.submenu_item = gui.mainFrame.sysTrayIcon.menu.Insert(2, wx.ID_ANY, _("WorldVoice"), self.submenu_vocalizer)

	def removeMenu(self):
		if self.submenu_item is not None:
			try:
				gui.mainFrame.sysTrayIcon.menu.Remove(self.submenu_item)
			except AttributeError:  # We can get this somehow from wx python when NVDA is shuttingdown, just ignore
				pass
			self.submenu_item.Destroy()

	def fileImport(self, import_path):
		with wx.FileDialog(gui.mainFrame, message=_("Import file..."), wildcard="zip files (*.zip)|*.zip") as entryDialog:
			if entryDialog.ShowModal() != wx.ID_OK:
				return

			path = entryDialog.GetPath()
			try:
				from zipfile import ZipFile
				with ZipFile(path, 'r') as core_file:
					core_file.testzip()
					core_file.extractall(import_path)
			except BaseException:
				gui.messageBox(
					_("Import fail"),
					_("Import File"), wx.OK
				)
			else:
				if gui.messageBox(
					_("For the new file to import, NVDA must be restarted. Are you want to restart NVDA now ?"),
					_("Import File"), wx.OK | wx.CANCEL | wx.ICON_WARNING
				) == wx.OK:
					import core
					import queueHandler
					queueHandler.queueFunction(queueHandler.eventQueue, core.restart)

	def onFileImport(self, event):
		self.fileImport(workspace_path)

	def onAisoundCoreInstall(self, event):
		self.fileImport(AisoundVoice.workspace)

	def popup_SpeechSettingsDialog(self, event):
		wx.CallAfter(gui.mainFrame._popupSettingsDialog, WorldVoiceSettingsDialog)

	def popup_SpeechSymbolsDialog(self, event):
		if SpeechSymbolsDialog._instance is None:
			gui.mainFrame._popupSettingsDialog(SpeechSymbolsDialog)
		else:
			ui.message(_("SpeechSymbolsDialog have already been opened"))

	@script(
		description=_("popup speech settings dialog"),
		category=ADDON_SUMMARY,
	)
	def script_popup_SpeechSettingsDialog(self, gesture):
		self.popup_SpeechSettingsDialog(None)

	@script(
		description=_("popup unicode settings dialog"),
		category=ADDON_SUMMARY,
	)
	def script_popup_SpeechSymbolsDialog(self, gesture):
		self.popup_SpeechSymbolsDialog(None)
