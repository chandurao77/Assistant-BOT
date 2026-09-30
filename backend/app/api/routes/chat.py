"""Streaming chat endpoint — Server-Sent Events."""
from __future__ import annotations
import json
import logging
import time
import uuid

import httpx
from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from app.api.dependencies import get_optional_user
from app.config import get_settings
from app.models.schemas import ChatRequest
from app.services.input_guardrail import InputGuardrail

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

_input_guardrail = InputGuardrail()


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    user: dict | None = Depends(get_optional_user),
):
    """
    Stream an answer to a natural language question as Server-Sent Events.

    Event types emitted:
    - ``token``   — incremental answer text
    - ``sources`` — JSON array of SourceDocument after generation is complete
    - ``error``   — error message string
    - ``done``    — signals stream end (empty data)
    """
    conversation_id = body.conversation_id or str(uuid.uuid4())
    pipeline = request.app.state.pipeline
    store = request.app.state.conversation_store
    settings = get_settings()
    user_id = user["id"] if user else None

    # ── Role-based space filtering ────────────────────────────────────
    allowed_spaces = user.get("allowed_spaces", []) if user else []
    effective_space_keys = body.space_keys
    if allowed_spaces:
        if effective_space_keys:
            effective_space_keys = [k for k in effective_space_keys if k in allowed_spaces]
        else:
            effective_space_keys = allowed_spaces

    # Load and truncate history from SQLite
    max_turns = settings.max_history_turns
    raw_history = await store.get_history(conversation_id)
    history_truncated = False
    if max_turns > 0 and raw_history and len(raw_history) > max_turns * 2:
        history = raw_history[-(max_turns * 2):]
        history_truncated = True
    else:
        history = raw_history or None

    logger.info(
        "[%s] chat/stream question=%r history_turns=%d",
        conversation_id, body.question[:80], len(raw_history) // 2,
    )

    # Spell-correct question before embedding (no-op if already clean)
    corrected_question, original_question = await pipeline.prepare_query(body.question)

    # Message IDs generated here so the SSE response can include them for feedback
    user_msg_id = str(uuid.uuid4())
    assistant_msg_id = str(uuid.uuid4())

    # Small-talk phrases that should receive a friendly conversational reply
    # instead of going through the full RAG pipeline.
    # ── Small-talk response dictionary ───────────────────────────────────
    # ── Small-talk response templates ──────────────────────────────────────
    _GREETING = "Hi there! I'm Assistant Bot. Ask me anything about your documents — handbooks, runbooks, guides, and more."
    _THANKS = "You're welcome! Let me know if there's anything else I can look up in the documentation."
    _BYE = "Goodbye! Come back anytime you have questions about the documentation."
    _HOWRU = "I'm doing great and ready to help! Ask me anything about your documents."
    _OK = "Got it! Let me know if you have any questions about the documentation."
    _YES = "Great! What would you like to know about your documents?"
    _NO = "No problem! I'm here whenever you need to look something up."
    _USAGE = (
        "Just type your question in plain English! For example:\n"
        "• \"How do I set up VPN?\"\n"
        "• \"What is the PTO policy?\"\n"
        "• \"Summarise the release process\"\n"
        "I'll search your ingested documents and give you an answer with source links."
    )
    _HELP = (
        "I can help you find information in your documentation. "
        "Here are some things you can ask me:\n"
        "• \"How do I set up the dev environment?\"\n"
        "• \"What is the onboarding process for new hires?\"\n"
        "• \"Summarise the release process\"\n"
        "Just ask in plain English and I'll search through all ingested spaces."
    )
    _WHOAMI = (
        "I'm Assistant Bot, your documentation assistant! "
        "I'm an AI assistant built on your own documentation. "
        "I use Retrieval-Augmented Generation (RAG) to find and synthesise answers "
        "from your document collection — I only answer from content that's been ingested, "
        "so my answers are always grounded in your actual docs."
    )
    _ABOUT_BOT = (
        "I'm **Assistant Bot**, a knowledge assistant that answers questions from your own documents. "
        "Ask me anything about the documentation you've ingested!"
    )
    _SORRY = "No need to apologise! I'm here to help. What would you like to know?"
    _LAUGH = "Glad I could help! 😄 Got any questions about the docs?"
    _COMPLIMENT = "Thank you, that's kind! I'm here to help — ask me anything about your documents."
    _PERSONAL = "Great question, but I'm only able to help with your documentation! Try asking about policies, guides, or processes."
    _REPEAT = "Sure — could you rephrase your question? I'll search the docs again for you."
    _WAIT = "Take your time! I'll be right here when you're ready to ask."
    _AGREE = "Glad we're on the same page! Anything else you'd like to look up?"
    _DISAGREE = "I understand. Would you like me to search for something different?"
    _CONFUSED = "I might have been unclear — could you rephrase your question? I'll do my best to find the right answer in the docs."
    _PROFANITY = "I'd prefer to keep things professional. 😊 How can I help you with the documentation?"
    _EMOJI_REPLY = "😊 How can I help you with the documentation today?"
    _TESTING = "Looks like you're testing me! I'm working fine. Ask me anything about your documents."
    _BORED = "Let's fix that! Here are some things you can explore:\n• \"What's the onboarding process?\"\n• \"How do I request PTO?\"\n• \"What are the coding standards?\""

    # ── Small-talk dictionary (~500+ entries) ──────────────────────────────
    # Python dict lookup is O(1) — zero performance impact regardless of size.
    _SMALL_TALK_RESPONSES: dict[str, str] = {
        # ─── Greetings (50+) ───────────────────────────────────────────────
        "hello": _GREETING, "hi": _GREETING, "hey": _GREETING, "hiya": _GREETING,
        "howdy": _GREETING, "yo": _GREETING, "sup": _GREETING, "hola": _GREETING,
        "greetings": _GREETING, "welcome": _GREETING, "hi there": _GREETING,
        "hey there": _GREETING, "hello there": _GREETING, "what's good": _GREETING,
        "whats good": _GREETING, "aloha": _GREETING, "bonjour": _GREETING,
        "namaste": _GREETING, "salaam": _GREETING, "ciao": _GREETING,
        "konnichiwa": _GREETING, "ahoy": _GREETING, "heya": _GREETING,
        "hallo": _GREETING, "wassup": _GREETING, "wazzup": _GREETING,
        "what's happening": _GREETING, "whats happening": _GREETING,
        "what's crackin": _GREETING, "what's crackin'": _GREETING,
        "what's cracking": _GREETING, "what it do": _GREETING,
        "well hello": _GREETING, "oh hello": _GREETING, "oh hi": _GREETING,
        "oh hey": _GREETING, "hi hi": _GREETING, "hey hey": _GREETING,
        "hello hello": _GREETING, "heyy": _GREETING, "heyyy": _GREETING,
        "hii": _GREETING, "hiii": _GREETING, "helloo": _GREETING, "hellooo": _GREETING,
        "hiiii": _GREETING, "ello": _GREETING, "henlo": _GREETING, "hewwo": _GREETING,
        "g'day": _GREETING, "gday": _GREETING, "top of the morning": _GREETING,
        "salutations": _GREETING, "hullo": _GREETING, "hai": _GREETING,
        "hey yo": _GREETING, "yo yo": _GREETING, "whaddup": _GREETING,
        "what up": _GREETING, "good day": _GREETING, "good to see you": _GREETING,
        "nice to meet you": _GREETING, "pleased to meet you": _GREETING,
        "long time no see": _GREETING, "hey buddy": _GREETING, "hi buddy": _GREETING,
        "hey friend": _GREETING, "hi friend": _GREETING, "hello friend": _GREETING,
        "hi bot": _GREETING, "hello bot": _GREETING, "hey bot": _GREETING,
        "hi assistant bot": _GREETING, "hello assistant bot": _GREETING, "hey assistant bot": _GREETING,
        "hi assistant": _GREETING, "hello assistant": _GREETING,
        "hey assistant": _GREETING, "hi ai": _GREETING, "hello ai": _GREETING,

        # ─── Thanks (40+) ─────────────────────────────────────────────────
        "thanks": _THANKS, "thank you": _THANKS, "thank": _THANKS, "thx": _THANKS,
        "thanks a lot": _THANKS, "thank you so much": _THANKS, "ty": _THANKS,
        "much appreciated": _THANKS, "appreciate it": _THANKS, "cheers": _THANKS,
        "thanks much": _THANKS, "thanks a bunch": _THANKS, "thanks a ton": _THANKS,
        "many thanks": _THANKS, "thanx": _THANKS, "thankz": _THANKS,
        "thanks so much": _THANKS, "thanks for that": _THANKS,
        "thanks for the help": _THANKS, "thanks for helping": _THANKS,
        "thanks for your help": _THANKS, "thank you for your help": _THANKS,
        "thank you very much": _THANKS, "thank you for that": _THANKS,
        "thank you kindly": _THANKS, "thanks kindly": _THANKS,
        "i appreciate it": _THANKS, "i appreciate that": _THANKS,
        "appreciate your help": _THANKS, "i appreciate your help": _THANKS,
        "ta": _THANKS, "ta very much": _THANKS, "danke": _THANKS,
        "gracias": _THANKS, "merci": _THANKS, "arigato": _THANKS,
        "thanks mate": _THANKS, "thanks buddy": _THANKS, "thanks friend": _THANKS,
        "thanks bro": _THANKS, "thanks man": _THANKS, "thanks pal": _THANKS,
        "that was helpful": _THANKS, "very helpful": _THANKS, "so helpful": _THANKS,
        "that helped": _THANKS, "this helped": _THANKS, "helpful": _THANKS,

        # ─── Goodbye (35+) ────────────────────────────────────────────────
        "bye": _BYE, "goodbye": _BYE, "good bye": _BYE, "cya": _BYE,
        "see you": _BYE, "see ya": _BYE, "later": _BYE, "take care": _BYE,
        "ttyl": _BYE, "byebye": _BYE, "bye bye": _BYE, "bbye": _BYE,
        "bye for now": _BYE, "goodbye for now": _BYE, "see you later": _BYE,
        "see you around": _BYE, "see you soon": _BYE, "see ya later": _BYE,
        "catch you later": _BYE, "catch ya later": _BYE, "until next time": _BYE,
        "talk later": _BYE, "talk to you later": _BYE, "gtg": _BYE,
        "gotta go": _BYE, "got to go": _BYE, "i gotta go": _BYE,
        "i'm leaving": _BYE, "im leaving": _BYE, "i'm done": _BYE, "im done": _BYE,
        "i'm out": _BYE, "im out": _BYE, "peace": _BYE, "peace out": _BYE,
        "adios": _BYE, "au revoir": _BYE, "sayonara": _BYE, "toodles": _BYE,
        "have a good day": _BYE, "have a nice day": _BYE, "have a great day": _BYE,
        "have a good one": _BYE, "take it easy": _BYE, "so long": _BYE,

        # ─── How are you (30+) ────────────────────────────────────────────
        "how are you": _HOWRU, "how are you doing": _HOWRU, "whats up": _HOWRU,
        "what's up": _HOWRU, "how's it going": _HOWRU, "hows it going": _HOWRU,
        "how do you do": _HOWRU, "how are things": _HOWRU, "how's things": _HOWRU,
        "how's everything": _HOWRU, "hows everything": _HOWRU,
        "how are you today": _HOWRU, "how are you doing today": _HOWRU,
        "how you doing": _HOWRU, "how ya doing": _HOWRU,
        "how goes it": _HOWRU, "how's life": _HOWRU, "hows life": _HOWRU,
        "are you there": _HOWRU, "are you here": _HOWRU, "you there": _HOWRU,
        "are you online": _HOWRU, "are you alive": _HOWRU, "are you awake": _HOWRU,
        "are you working": _HOWRU, "are you up": _HOWRU, "you up": _HOWRU,
        "are you busy": _HOWRU, "are you available": _HOWRU, "are you free": _HOWRU,
        "you okay": _HOWRU, "are you okay": _HOWRU, "are you alright": _HOWRU,
        "how's your day": _HOWRU, "hows your day": _HOWRU,

        # ─── Acknowledgment (35+) ────────────────────────────────────────
        "ok": _OK, "okay": _OK, "cool": _OK, "got it": _OK, "understood": _OK,
        "nice": _OK, "great": _OK, "perfect": _OK, "alright": _OK, "k": _OK,
        "kk": _OK, "okey": _OK, "okie": _OK, "okk": _OK, "okaay": _OK,
        "roger": _OK, "roger that": _OK, "copy": _OK, "copy that": _OK,
        "10-4": _OK, "noted": _OK, "i see": _OK, "i understand": _OK,
        "makes sense": _OK, "that makes sense": _OK, "i get it": _OK,
        "fair enough": _OK, "right": _OK, "right on": _OK,
        "sounds good": _OK, "sounds great": _OK, "sounds fine": _OK,
        "all good": _OK, "all clear": _OK, "i got it": _OK,
        "gotcha": _OK, "gotchu": _OK, "word": _OK, "aight": _OK,
        "aye": _OK, "aye aye": _OK, "affirmative": _OK,

        # ─── Affirmation (25+) ───────────────────────────────────────────
        "yes": _YES, "yeah": _YES, "yep": _YES, "sure": _YES, "yup": _YES,
        "yea": _YES, "ya": _YES, "yah": _YES, "yas": _YES, "yass": _YES,
        "yess": _YES, "yesss": _YES, "yes please": _YES, "yeah sure": _YES,
        "yep yep": _YES, "yes yes": _YES, "of course": _YES, "absolutely": _YES,
        "definitely": _YES, "for sure": _YES, "sure thing": _YES,
        "why not": _YES, "go ahead": _YES, "go for it": _YES, "do it": _YES,
        "please": _YES, "please do": _YES, "yes sir": _YES, "yes ma'am": _YES,

        # ─── Negation (30+) ──────────────────────────────────────────────
        "no": _NO, "nope": _NO, "nah": _NO, "nevermind": _NO, "never mind": _NO,
        "cancel": _NO, "nothing": _NO, "nm": _NO,
        "naw": _NO, "nuh uh": _NO, "no thanks": _NO, "no thank you": _NO,
        "no thank": _NO, "not really": _NO, "not now": _NO, "not yet": _NO,
        "nada": _NO, "negative": _NO, "forget it": _NO, "forget about it": _NO,
        "don't bother": _NO, "dont bother": _NO, "no worries": _NO,
        "it's fine": _NO, "its fine": _NO, "it's ok": _NO, "its ok": _NO,
        "it's okay": _NO, "its okay": _NO, "doesn't matter": _NO,
        "doesnt matter": _NO, "skip": _NO, "pass": _NO, "none": _NO,
        "i'm good": _NO, "im good": _NO, "all set": _NO, "no need": _NO,
        "that's all": _NO, "thats all": _NO, "that's it": _NO, "thats it": _NO,
        "i'm fine": _NO, "im fine": _NO, "no more questions": _NO,
        "nothing else": _NO, "that will be all": _NO, "no more": _NO,

        # ─── Apology (25+) ──────────────────────────────────────────────
        "sorry": _SORRY, "i'm sorry": _SORRY, "im sorry": _SORRY,
        "my bad": _SORRY, "my mistake": _SORRY, "apologies": _SORRY,
        "i apologize": _SORRY, "i apologise": _SORRY, "pardon": _SORRY,
        "pardon me": _SORRY, "excuse me": _SORRY, "forgive me": _SORRY,
        "oops": _SORRY, "oopsie": _SORRY, "whoops": _SORRY, "whoopsie": _SORRY,
        "my fault": _SORRY, "sorry about that": _SORRY, "so sorry": _SORRY,
        "sorry for that": _SORRY, "i messed up": _SORRY, "i made a mistake": _SORRY,
        "wrong question": _SORRY, "wrong chat": _SORRY, "ignore that": _SORRY,
        "disregard": _SORRY, "disregard that": _SORRY,

        # ─── Laughter (20+) ─────────────────────────────────────────────
        "lol": _LAUGH, "lmao": _LAUGH, "haha": _LAUGH, "hahaha": _LAUGH,
        "hahahaha": _LAUGH, "ha": _LAUGH, "ha ha": _LAUGH, "ha ha ha": _LAUGH,
        "hehe": _LAUGH, "hehehe": _LAUGH, "hihi": _LAUGH, "rofl": _LAUGH,
        "xd": _LAUGH, "lolol": _LAUGH, "lolz": _LAUGH, "lulz": _LAUGH,
        "funny": _LAUGH, "that's funny": _LAUGH, "thats funny": _LAUGH,
        "so funny": _LAUGH, "too funny": _LAUGH, "you're funny": _LAUGH,
        "youre funny": _LAUGH,

        # ─── Compliments (25+) ──────────────────────────────────────────
        "good job": _COMPLIMENT, "well done": _COMPLIMENT, "nice job": _COMPLIMENT,
        "great job": _COMPLIMENT, "awesome": _COMPLIMENT, "amazing": _COMPLIMENT,
        "brilliant": _COMPLIMENT, "excellent": _COMPLIMENT, "fantastic": _COMPLIMENT,
        "wonderful": _COMPLIMENT, "superb": _COMPLIMENT, "outstanding": _COMPLIMENT,
        "you're awesome": _COMPLIMENT, "youre awesome": _COMPLIMENT,
        "you're great": _COMPLIMENT, "youre great": _COMPLIMENT,
        "you're amazing": _COMPLIMENT, "youre amazing": _COMPLIMENT,
        "you're the best": _COMPLIMENT, "youre the best": _COMPLIMENT,
        "you rock": _COMPLIMENT, "love it": _COMPLIMENT, "love this": _COMPLIMENT,
        "impressive": _COMPLIMENT, "genius": _COMPLIMENT, "smart": _COMPLIMENT,
        "you're smart": _COMPLIMENT, "youre smart": _COMPLIMENT,
        "good bot": _COMPLIMENT, "nice one": _COMPLIMENT, "bravo": _COMPLIMENT,
        "kudos": _COMPLIMENT, "keep it up": _COMPLIMENT, "way to go": _COMPLIMENT,

        # ─── Personal / off-topic (30+) ─────────────────────────────────
        "what's the weather": _PERSONAL, "whats the weather": _PERSONAL,
        "how's the weather": _PERSONAL, "hows the weather": _PERSONAL,
        "what's the time": _PERSONAL, "whats the time": _PERSONAL,
        "what time is it": _PERSONAL, "what day is it": _PERSONAL,
        "what's the date": _PERSONAL, "whats the date": _PERSONAL,
        "tell me a joke": _PERSONAL, "tell me a story": _PERSONAL,
        "tell me something funny": _PERSONAL, "tell me something interesting": _PERSONAL,
        "sing a song": _PERSONAL, "tell me a riddle": _PERSONAL,
        "what's your name": _PERSONAL, "whats your name": _PERSONAL,
        "how old are you": _PERSONAL, "where are you from": _PERSONAL,
        "where do you live": _PERSONAL, "do you have feelings": _PERSONAL,
        "are you human": _PERSONAL, "are you a bot": _PERSONAL,
        "are you a robot": _PERSONAL, "are you real": _PERSONAL,
        "are you ai": _PERSONAL, "are you an ai": _PERSONAL,
        "are you chatgpt": _PERSONAL, "are you gpt": _PERSONAL,
        "do you like me": _PERSONAL, "do you dream": _PERSONAL,
        "do you sleep": _PERSONAL, "what's your favorite color": _PERSONAL,
        "what do you eat": _PERSONAL, "are you sentient": _PERSONAL,

        # ─── Repeat / clarify (15+) ─────────────────────────────────────
        "what": _REPEAT, "huh": _REPEAT, "come again": _REPEAT,
        "say that again": _REPEAT, "repeat that": _REPEAT,
        "can you repeat that": _REPEAT, "i didn't understand": _REPEAT,
        "i didnt understand": _REPEAT, "i don't understand": _REPEAT,
        "i dont understand": _REPEAT, "what do you mean": _REPEAT,
        "can you clarify": _REPEAT, "please clarify": _REPEAT,
        "explain": _REPEAT, "elaborate": _REPEAT, "be more specific": _REPEAT,
        "what did you say": _REPEAT, "i'm confused": _REPEAT, "im confused": _REPEAT,

        # ─── Wait / thinking (15+) ──────────────────────────────────────
        "wait": _WAIT, "hold on": _WAIT, "one moment": _WAIT, "one sec": _WAIT,
        "one second": _WAIT, "just a sec": _WAIT, "just a moment": _WAIT,
        "give me a sec": _WAIT, "give me a moment": _WAIT, "give me a minute": _WAIT,
        "hang on": _WAIT, "brb": _WAIT, "be right back": _WAIT,
        "let me think": _WAIT, "thinking": _WAIT, "hmm": _WAIT, "hmmm": _WAIT,
        "hmmmm": _WAIT, "umm": _WAIT, "ummm": _WAIT, "um": _WAIT, "uh": _WAIT,

        # ─── Agreement (15+) ────────────────────────────────────────────
        "i agree": _AGREE, "agreed": _AGREE, "exactly": _AGREE,
        "exactly right": _AGREE, "precisely": _AGREE, "spot on": _AGREE,
        "that's right": _AGREE, "thats right": _AGREE, "correct": _AGREE,
        "that's correct": _AGREE, "thats correct": _AGREE, "true": _AGREE,
        "that's true": _AGREE, "thats true": _AGREE, "indeed": _AGREE,
        "you're right": _AGREE, "youre right": _AGREE, "bingo": _AGREE,
        "nailed it": _AGREE, "on point": _AGREE,

        # ─── Disagreement (15+) ─────────────────────────────────────────
        "i disagree": _DISAGREE, "not quite": _DISAGREE, "not exactly": _DISAGREE,
        "that's wrong": _DISAGREE, "thats wrong": _DISAGREE,
        "that's not right": _DISAGREE, "thats not right": _DISAGREE,
        "that's incorrect": _DISAGREE, "thats incorrect": _DISAGREE,
        "wrong": _DISAGREE, "incorrect": _DISAGREE, "false": _DISAGREE,
        "not true": _DISAGREE, "that's not true": _DISAGREE,
        "i don't think so": _DISAGREE, "i dont think so": _DISAGREE,
        "are you sure": _DISAGREE, "really": _DISAGREE,

        # ─── Confusion / gibberish (15+) ────────────────────────────────
        "asdf": _CONFUSED, "asdfg": _CONFUSED, "asdfjkl": _CONFUSED,
        "qwerty": _CONFUSED, "jkl": _CONFUSED, "fdsa": _CONFUSED,
        "abc": _CONFUSED, "abcd": _CONFUSED, "123": _CONFUSED, "1234": _CONFUSED,
        "aaa": _CONFUSED, "aaaa": _CONFUSED, "bbb": _CONFUSED,
        "zzz": _CONFUSED, "zzzz": _CONFUSED, "blah": _CONFUSED,
        "blah blah": _CONFUSED, "blah blah blah": _CONFUSED,
        "foo": _CONFUSED, "bar": _CONFUSED, "foobar": _CONFUSED,
        "test": _TESTING, "testing": _TESTING, "test test": _TESTING,
        "testing testing": _TESTING, "hello world": _TESTING,
        "is this working": _TESTING, "does this work": _TESTING,
        "are you working": _TESTING, "can you hear me": _TESTING,

        # ─── Profanity deflection (light) ───────────────────────────────
        "damn": _PROFANITY, "dammit": _PROFANITY, "crap": _PROFANITY,
        "wtf": _PROFANITY, "omg": _PROFANITY, "ugh": _PROFANITY,
        "this sucks": _PROFANITY, "this is bad": _PROFANITY,
        "you suck": _PROFANITY, "you're bad": _PROFANITY, "youre bad": _PROFANITY,
        "stupid": _PROFANITY, "dumb": _PROFANITY, "useless": _PROFANITY,
        "terrible": _PROFANITY, "horrible": _PROFANITY, "awful": _PROFANITY,
        "worst": _PROFANITY, "the worst": _PROFANITY,
        "you're useless": _PROFANITY, "youre useless": _PROFANITY,
        "you're stupid": _PROFANITY, "youre stupid": _PROFANITY,
        "not helpful": _PROFANITY, "unhelpful": _PROFANITY,

        # ─── Emoji text (10+) ──────────────────────────────────────────
        ":)": _EMOJI_REPLY, ":-)": _EMOJI_REPLY, ":(": _EMOJI_REPLY,
        ":-(": _EMOJI_REPLY, ":d": _EMOJI_REPLY, ":p": _EMOJI_REPLY,
        ";)": _EMOJI_REPLY, "<3": _EMOJI_REPLY, "xd": _LAUGH,
        ":o": _EMOJI_REPLY, "o_o": _EMOJI_REPLY, "^^": _EMOJI_REPLY,

        # ─── Boredom (10+) ─────────────────────────────────────────────
        "i'm bored": _BORED, "im bored": _BORED, "bored": _BORED,
        "boring": _BORED, "nothing to do": _BORED, "i have nothing to do": _BORED,
        "entertain me": _BORED, "amuse me": _BORED,
        "what should i do": _BORED, "any suggestions": _BORED,
        "suggest something": _BORED, "give me ideas": _BORED,

        # ─── Help / Usage (extended) ────────────────────────────────────
        "help": _HELP, "what can you do": _HELP, "what can you help with": _HELP,
        "please help": _HELP, "i need help": _HELP, "can you help me": _HELP,
        "can you help": _HELP, "help me": _HELP, "help me please": _HELP,
        "i need assistance": _HELP, "assist me": _HELP, "assistance": _HELP,
        "what do you do": _HELP, "your capabilities": _HELP,
        "what are your capabilities": _HELP, "features": _HELP,
        "what features do you have": _HELP, "show me what you can do": _HELP,

        # ─── How to use (extended) ──────────────────────────────────────
        "how does this work": _USAGE, "how do i use this": _USAGE,
        "how to use": _USAGE, "how to use this": _USAGE,
        "what topics do you cover": _USAGE, "what do you know about": _USAGE,
        "what can i ask": _USAGE, "what should i ask": _USAGE,
        "how do i ask": _USAGE, "how do i search": _USAGE,
        "how to search": _USAGE, "how to ask": _USAGE,
        "what kind of questions": _USAGE, "what questions can i ask": _USAGE,
        "what do you know": _USAGE, "what information do you have": _USAGE,
        "what docs do you have": _USAGE, "what documentation": _USAGE,
        "what spaces": _USAGE, "which spaces": _USAGE,
        "instructions": _USAGE, "guide me": _USAGE,

        # ─── Identity (extended) ────────────────────────────────────────
        "who are you": _WHOAMI, "what are you": _WHOAMI,
        "who made you": _WHOAMI, "who built you": _WHOAMI,
        "who created you": _WHOAMI, "what are you made of": _WHOAMI,
        "what technology do you use": _WHOAMI, "what model are you": _WHOAMI,
        "what llm do you use": _WHOAMI, "how do you work": _WHOAMI,
        "how were you built": _WHOAMI, "tell me about yourself": _WHOAMI,
        "introduce yourself": _WHOAMI, "describe yourself": _WHOAMI,

        # ─── About Assistant Bot (extended) ─────────────────────────────────────
        "what does assistant bot stand for": _ABOUT_BOT, "what does assistant bot mean": _ABOUT_BOT,
        "what is assistant bot": _ABOUT_BOT, "assistant bot meaning": _ABOUT_BOT,
        "assistant bot stand for": _ABOUT_BOT, "assistant bot acronym": _ABOUT_BOT,
        "tell me about assistant bot": _ABOUT_BOT, "tell me about assistant bot application": _ABOUT_BOT,
        "about assistant bot": _ABOUT_BOT, "what is this": _ABOUT_BOT,
        "what is this app": _ABOUT_BOT, "what is this application": _ABOUT_BOT,
        "what is this tool": _ABOUT_BOT, "what is this chatbot": _ABOUT_BOT,
        "what is this bot": _ABOUT_BOT, "what app is this": _ABOUT_BOT,
        "what tool is this": _ABOUT_BOT, "assistant bot": _ABOUT_BOT,

        # ─── SelectionPopup follow-ups ──────────────────────────────────
        'tell me more about: "assistant bot"': _ABOUT_BOT,
        "tell me more about: 'assistant bot'": _ABOUT_BOT,
        "tell me more about assistant bot": _ABOUT_BOT,
        'tell me more about: "assistant bot application"': _ABOUT_BOT,
        "tell me more about: assistant bot": _ABOUT_BOT,
    }

    # Time-of-day greetings get a dynamic reply
    _TIME_GREETINGS = {"good morning", "good afternoon", "good evening", "good night"}

    def _is_small_talk(text: str) -> bool:
        normalised = text.lower().strip().rstrip("!?.,")
        if normalised in _SMALL_TALK_RESPONSES or normalised in _TIME_GREETINGS:
            return True
        # Also catch SelectionPopup follow-up questions about Assistant Bot itself
        normalised_noquote = normalised.replace('"', '').replace("'", "")
        return normalised_noquote in _SMALL_TALK_RESPONSES

    async def event_generator():
        answer_tokens: list[str] = []
        sources_found = 0
        answered = True
        _analytics_sources: list[dict] | None = None
        _start_time = time.monotonic()
        try:
            # ── Input guardrail: block prompt injection attempts ───────────
            is_blocked, pattern_name = _input_guardrail.check(body.question)
            if is_blocked:
                reply = (
                    "I'm sorry, but I can't process that request. "
                    "I'm designed to answer questions about your documentation. "
                    "Please rephrase your question."
                )
                yield {
                    "event": "token",
                    "data": json.dumps({
                        "text": reply,
                        "conversation_id": conversation_id,
                        "assistant_msg_id": assistant_msg_id,
                    }),
                }
                await store.append_turn(
                    conversation_id,
                    title=body.question[:60].strip(),
                    user_content=body.question,
                    assistant_content=reply,
                    user_msg_id=user_msg_id,
                    assistant_msg_id=assistant_msg_id,                    user_id=user_id,                )
                yield {"event": "sources", "data": json.dumps([])}
                await store.record_query_analytics(body.question, 0, False,
                    response_ms=int((time.monotonic() - _start_time) * 1000),
                    user_id=user_id, space_keys=effective_space_keys)
                yield {"event": "done", "data": ""}
                return

            # ── Small-talk bypass ──────────────────────────────────────────
            if _is_small_talk(body.question):
                normalised = body.question.lower().strip().rstrip("!?.,")
                # Time-of-day greetings get a dynamic reply
                if normalised in _TIME_GREETINGS:
                    reply = f"{body.question.strip().rstrip('!?.,').title()}! How can I help you with the documentation today?"
                else:
                    # Look up in dictionary (also try without quotes for SelectionPopup)
                    reply = _SMALL_TALK_RESPONSES.get(normalised)
                    if reply is None:
                        normalised_noquote = normalised.replace('"', '').replace("'", "")
                        reply = _SMALL_TALK_RESPONSES.get(normalised_noquote, _GREETING)

                yield {
                    "event": "token",
                    "data": json.dumps({
                        "text": reply,
                        "conversation_id": conversation_id,
                        "assistant_msg_id": assistant_msg_id,
                    }),
                }
                # Persist the small-talk turn so it appears in the sidebar
                await store.append_turn(
                    conversation_id,
                    title=body.question[:60].strip(),
                    user_content=body.question,
                    assistant_content=reply,
                    user_msg_id=user_msg_id,
                    assistant_msg_id=assistant_msg_id,
                    user_id=user_id,
                )
                yield {"event": "sources", "data": json.dumps([])}
                await store.record_query_analytics(body.question, 0, True,
                    response_ms=int((time.monotonic() - _start_time) * 1000),
                    user_id=user_id, space_keys=effective_space_keys)
                yield {"event": "done", "data": ""}
                return
            # ───────────────────────────────────────────────────────────────

            # Notify client if query was auto-corrected
            if original_question:
                yield {
                    "event": "query_corrected",
                    "data": json.dumps({
                        "original": original_question,
                        "corrected": corrected_question,
                    }),
                }

            # Notify client if history was truncated
            if history_truncated:
                yield {
                    "event": "status",
                    "data": json.dumps({
                        "step": "history_truncated",
                        "message": f"Long conversation — using last {max_turns} turns for context.",
                    }),
                }

            # ── Progress: Searching documents ──
            yield {
                "event": "status",
                "data": json.dumps({"step": "searching", "message": "Searching documents..."}),
            }

            generating_notified = False
            entity_store = getattr(request.app.state, "entity_store", None)
            async for token, sources in pipeline.stream(
                corrected_question,
                history=history,
                space_keys=effective_space_keys,
                request_id=conversation_id,
                conversation_store=store,
                entity_store=entity_store,
                force_fresh=body.force_fresh,
                skip_rewrite=body.skip_rewrite,
                original_question=original_question,
            ):
                if sources is not None:
                    sources_found = len(sources)
                    answered = sources_found > 0
                    # Persist this turn to SQLite
                    full_answer = "".join(answer_tokens)
                    title = body.question[:60].strip()
                    await store.append_turn(
                        conversation_id,
                        title=title,
                        user_content=body.question,
                        assistant_content=full_answer,
                        user_msg_id=user_msg_id,
                        assistant_msg_id=assistant_msg_id,
                        user_id=user_id,
                    )

                    # Emit citations — exclude 'content' (full text, only needed for LLM)
                    # Filter: threshold 0.45, score gap cutoff 0.25 from top, cap at 5
                    _DISPLAY_THRESHOLD = 0.45
                    _MAX_DISPLAY_SOURCES = 5
                    _SCORE_GAP_CUTOFF = 0.20  # drop sources >0.20 below top (was 0.25)

                    ranked = sorted(sources, key=lambda s: s.score, reverse=True)
                    above_threshold = [s for s in ranked if s.score >= _DISPLAY_THRESHOLD]

                    # Apply score gap filter: cut off where gap from top exceeds cutoff
                    if above_threshold:
                        top_score = above_threshold[0].score
                        display_sources = []
                        for s in above_threshold[:_MAX_DISPLAY_SOURCES]:
                            if top_score - s.score > _SCORE_GAP_CUTOFF:
                                break
                            display_sources.append(s)
                    else:
                        display_sources = []

                    # If no sources pass, show top 2 with low confidence marker
                    if not display_sources and sources:
                        display_sources = ranked[:2]
                    source_dicts = [src.model_dump(exclude={"content"}) for src in display_sources]
                    # Store sources for analytics (title, url, score only)
                    _analytics_sources = [
                        {"title": src.title, "url": src.url, "score": round(src.score, 4)}
                        for src in display_sources
                    ]
                    # Compute answer confidence from displayed source scores
                    scores = [src.score for src in display_sources if src.score > 0]
                    avg_score = sum(scores) / len(scores) if scores else 0.0
                    spread = (max(scores) - min(scores)) if len(scores) > 1 else 1.0
                    if avg_score >= 0.75 and spread < 0.15:
                        confidence = "high"
                    elif avg_score >= 0.50:
                        confidence = "medium"
                    else:
                        confidence = "low"
                    yield {
                        "event": "sources",
                        "data": json.dumps(
                            {"sources": source_dicts, "confidence": confidence, "confidence_score": round(avg_score, 3)},
                            ensure_ascii=False,
                        ),
                    }
                elif token:
                    # ── Progress: Generating answer (once, on first token) ──
                    if not generating_notified:
                        generating_notified = True
                        yield {
                            "event": "status",
                            "data": json.dumps({"step": "generating", "message": "Generating answer..."}),
                        }
                    answer_tokens.append(token)
                    yield {
                        "event": "token",
                        "data": json.dumps({
                            "text": token,
                            "conversation_id": conversation_id,
                            "assistant_msg_id": assistant_msg_id,
                        }),
                    }
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            logger.error(
                "[%s] Service unavailable (%s) for question %r",
                conversation_id, type(exc).__name__, body.question[:60],
            )
            yield {
                "event": "error",
                "data": json.dumps({"message": "AI service is temporarily unavailable. Please try again in a moment."}),
            }
        except httpx.ReadTimeout as exc:
            logger.error(
                "[%s] LLM timeout for question %r",
                conversation_id, body.question[:60],
            )
            yield {
                "event": "error",
                "data": json.dumps({"message": "The request timed out. Please try a shorter or simpler question."}),
            }
        except Exception as exc:
            logger.exception(
                "[%s] RAG pipeline error (%s) for question %r",
                conversation_id, type(exc).__name__, body.question[:60],
            )
            yield {
                "event": "error",
                "data": json.dumps({"message": "An internal error occurred. Please try again."}),
            }
        finally:
            await store.record_query_analytics(body.question, sources_found, answered,
                response_ms=int((time.monotonic() - _start_time) * 1000),
                user_id=user_id, space_keys=effective_space_keys,
                sources=_analytics_sources)
            yield {"event": "done", "data": ""}

    return EventSourceResponse(event_generator(), ping=15)


@router.get("/suggestions")
async def get_suggestions(request: Request, q: str | None = None):
    """Return popular past questions as 'People also asked' suggestions."""
    store = request.app.state.conversation_store
    suggestions = await store.get_suggested_questions(current_question=q, limit=5)
    return {"suggestions": suggestions}
