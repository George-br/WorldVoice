# A part of NonVisual Desktop Access (NVDA)
# This file is covered by the GNU General Public License.
# See the file COPYING for more details.
# Copyright (C) 2006-2022 NV Access Limited, Peter Vágner, Aleksey Sadovoy, Babbage B.V., Bill Dengler,
# Julien Cochuyt


from typing import Callable, Optional
import weakref
from logHandler import log
import config
import controlTypes
import api
import textInfos
import queueHandler
import speech
from speech import sayAll
from speech.sayAll import CURSOR
from utils.security import objectBelowLockScreenAndWindowsIsLocked

from speech.commands import BreakCommand, CallbackCommand
from speech.speechWithoutPauses import SpeechWithoutPauses

from speech.types import (
	SpeechSequence,
	_flattenNestedSequences,
)


SayAllHandler = None


def initialize(
		speakFunc: Callable[[SpeechSequence], None],
		speakObject: 'speakObject',
		getTextInfoSpeech: 'getTextInfoSpeech',
		SpeakTextInfoState: 'SpeakTextInfoState',
):
	log.debug("Initializing sayAllHandler custom")
	global SayAllHandler
	sayAll.SayAllHandler = SayAllHandler = _SayAllHandler(
		SpeechWithoutPauses(speakFunc=speakFunc),
		speakObject,
		getTextInfoSpeech,
		SpeakTextInfoState,
	)


class _SayAllHandler(sayAll._SayAllHandler):
	def readObjects(self, obj: 'NVDAObjects.NVDAObject'):
		reader = _ObjectsReader(self, obj)
		self._getActiveSayAll = weakref.ref(reader)
		reader.next()

	def readText(
			self,
			cursor: CURSOR,
			startPos: Optional[textInfos.TextInfo] = None,
			nextLineFunc: Optional[Callable[[textInfos.TextInfo], textInfos.TextInfo]] = None,
			shouldUpdateCaret: bool = True,
	) -> None:
		self.lastSayAllMode = cursor
		try:
			if cursor == CURSOR.CARET:
				reader = _CaretTextReader(self)
			elif cursor == CURSOR.REVIEW:
				reader = _ReviewTextReader(self)
			elif cursor == CURSOR.TABLE:
				reader = _TableTextReader(self, startPos, nextLineFunc, shouldUpdateCaret)
			else:
				raise RuntimeError(f"Unknown cursor {cursor}")
		except NotImplementedError:
			log.debugWarning("Unable to make reader", exc_info=True)
			return
		self._getActiveSayAll = weakref.ref(reader)
		reader.nextLine()


class _TextReader(sayAll._TextReader):
	def nextLine(self):
		if not self.reader:
			log.debug("no self.reader")
			# We were stopped.
			return

		if (
			# The object died, so we should too.
			not self.reader.obj
			# SayAll is available on the lock screen via getSafeScripts, as such
			# ensure the say all reader does not contain secure information
			# before continuing
			or objectBelowLockScreenAndWindowsIsLocked(self.reader.obj)
		):
			log.debug("no self.reader.obj")
			self.finish()
			return

		if not self.initialIteration or not self.shouldReadInitialPosition():
			if not self.nextLineImpl():
				return
		self.initialIteration = False
		bookmark = self.reader.bookmark
		# Copy the speakTextInfoState so that speak callbackCommand
		# and its associated callback are using a copy isolated to this specific line.
		state = self.speakTextInfoState.copy()
		# Call lineReached when we start speaking this line.
		# lineReached will move the cursor and trigger reading of the next line.

		def _onLineReached(obj=self.reader.obj, state=state):
			self.lineReached(obj, bookmark, state)

		cb = CallbackCommand(
			_onLineReached,
			name="say-all:lineReached"
		)

		# Generate the speech sequence for the reader textInfo
		# and insert the lineReached callback at the very beginning of the sequence.
		# _linePrefix on speakTextInfo cannot be used here
		# As it would be inserted in the sequence after all initial control starts which is too late.
		speechGen = SayAllHandler._getTextInfoSpeech(
			self.reader,
			unit=textInfos.UNIT_READINGCHUNK,
			reason=controlTypes.OutputReason.SAYALL,
			useCache=state
		)
		seq = list(_flattenNestedSequences(speechGen))
		seq.insert(0, cb)
		seq.append(BreakCommand(300))
		# Speak the speech sequence.
		spoke = self.handler.speechWithoutPausesInstance.speakWithoutPauses(seq)
		# Update the textInfo state ready for when speaking the next line.
		self.speakTextInfoState = state.copy()

		if not self.collapseLineImpl():
			return

		if not spoke:
			# This line didn't include a natural pause, so nothing was spoken.
			self.numBufferedLines += 1
			if self.numBufferedLines < self.MAX_BUFFERED_LINES:
				# Move on to the next line.
				# We queue this to allow the user a chance to stop say all.
				queueHandler.queueFunction(queueHandler.eventQueue, self.nextLine)
			else:
				# We don't want to buffer too much.
				# Force speech. lineReached will resume things when speech catches up.
				self.handler.speechWithoutPausesInstance.speakWithoutPauses(None)
				# The first buffered line has now started speaking.
				self.numBufferedLines -= 1


class _CaretTextReader(_TextReader):
	def getInitialTextInfo(self) -> textInfos.TextInfo:
		try:
			return api.getCaretObject().makeTextInfo(textInfos.POSITION_CARET)
		except (NotImplementedError, RuntimeError) as e:
			raise NotImplementedError("Unable to make TextInfo: ", e)

	def updateCaret(self, updater: textInfos.TextInfo) -> None:
		updater.updateCaret()
		if config.conf["reviewCursor"]["followCaret"]:
			api.setReviewPosition(updater, isCaret=True)


class _ReviewTextReader(_TextReader):
	def getInitialTextInfo(self) -> textInfos.TextInfo:
		return api.getReviewPosition()

	def updateCaret(self, updater: textInfos.TextInfo) -> None:
		api.setReviewPosition(updater, isCaret=False)


class _TableTextReader(_CaretTextReader):
	def __init__(
			self,
			handler: _SayAllHandler,
			startPos: Optional[textInfos.TextInfo] = None,
			nextLineFunc: Optional[Callable[[textInfos.TextInfo], textInfos.TextInfo]] = None,
			shouldUpdateCaret: bool = True,
	):
		self.startPos = startPos
		self.nextLineFunc = nextLineFunc
		self.shouldUpdateCaret = shouldUpdateCaret
		super().__init__(handler)

	def getInitialTextInfo(self) -> textInfos.TextInfo:
		return self.startPos or super().getInitialTextInfo()

	def nextLineImpl(self) -> bool:
		try:
			self.reader = self.nextLineFunc(self.reader)
			return True
		except StopIteration:
			self.finish()
			return False

	def collapseLineImpl(self) -> bool:
		return True

	def shouldReadInitialPosition(self) -> bool:
		return True

	def updateCaret(self, updater: textInfos.TextInfo) -> None:
		if self.shouldUpdateCaret:
			return super().updateCaret(updater)


def patch():
	initialize(
		speech.speech.speak,
		speech.speech.speakObject,
		speech.speech.getTextInfoSpeech,
		speech.speech.SpeakTextInfoState,
	)


def unpatch():
	sayAll.initialize(
		speech.speech.speak,
		speech.speech.speakObject,
		speech.speech.getTextInfoSpeech,
		speech.speech.SpeakTextInfoState,
	)
