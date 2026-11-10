"""Conservative deterministic English/Hindi/Hinglish command recognition."""
import re


def _subtitle_option(text):
    if not re.search(r"\bsubtitles?\b", text):
        return None
    disabled = re.search(r"\b(?:without|no) subtitles?\b|\b(?:remove|disable|turn off|hata|nikal)\s+(?:the\s+)?subtitles?\b|\bsubtitles?\s+(?:remove|disable|hata|nikal)\b", text)
    return not bool(disabled)


def parse_command(text: str, activated: bool = True):
    """Typed/PTT input is activated; ambient input needs a leading wake word."""
    if not isinstance(text, str):
        return "unknown", {"heard": ""}
    t = re.sub(r"[^\w\s.+\-\u0900-\u097F]", " ", text.casefold())
    t = " ".join(t.split()).strip(' .।')
    # Whisper (or legacy KAAT) wake word. The phonetic variant "caught" is
    # accepted only for an explicitly activated command, never ambient input.
    wake = re.match(r"^(?:whisper|visper|whisp|hey whisper|ok whisper|hello whisper|kaat|काट|काट्|विस्पर" + (r'|caught' if activated else '') + r")\b[\s,.]*", t)
    if not activated and not wake:
        return "unknown", {"heard": text}
    if wake:
        t = t[wake.end():].strip()
    if not t:
        return "unknown", {"heard": text}
    if t in {'cancel', 'cancel command', 'stop listening', 'never mind'}:
        return 'cancel', {}
    # Unicode combining marks make Python's \b unsuitable for Hindi negation.
    negation = re.sub(r"\b(?:without|no) subtitles?\b", "", t)
    if "नहीं" in t or "मत" in t or re.search(r"\b(?:don t|dont|do not|not|no|mat|nahi|nahin|never)\b", negation):
        return "unknown", {"heard": text}
    from intent_parser import normalize_request, parse_common
    t = normalize_request(t)
    try:
        common = parse_common(t, original=text)
    except ValueError as exc:
        return 'unknown', {'reason':str(exc)}
    early_intents = {
        'help', 'cancel', 'close_recent', 'clarify_close', 'presentation',
        'identity', 'system_time', 'system_date', 'joke', 'status_check',
        'system_volume_up', 'system_volume_down', 'system_mute',
        'system_screenshot', 'system_minimize', 'close_application',
        'close_active_window', 'web_search', 'youtube_play',
        'open_application', 'open_website', 'open_folder'
    }
    if common and common[0] in early_intents:
        return common
    if re.search(r"\b(?:how|why|when|what|later|tomorrow|kya|kaise|kyun|kab)\b|\b(?:i|we|he|she|they) (?:will|would|said|think|should)\b", t):
        return "unknown", {"heard": text}
    if re.match(r"(?:i|we|he|she|they|main|hum)\b", t) and not t.startswith(("i want you to ", "i want to ")):
        return "unknown", {"heard": text}
    if any(s in t for s in ("क्या", "कैसे", "क्यों", "कल ", "मैं ", "हम ")) or re.search(r"\b(?:means|meaning|example|word|talking about)\b", t):
        return "unknown", {"heard": text}
    if common:
        return common
    t = re.sub(r"^(?:(?:i want you to|i want to|can you|could you|please|just|zara|bas|ab)\s+)+", "", t)
    for hindi, roman in (("खामोशी", "silence"), ("विराम", "pause"), ("हमेशा", "always"),
                         ("हटाओ", "remove"), ("हटा", "remove"), ("निकाल", "remove"),
                         ("आखिरी", "last"), ("सबटाइटल", "subtitles"), ("सेकंड", "seconds"),
                         ("रिकॉर्डिंग", "recording"), ("शुरू", "start"), ("जारी", "resume")):
        t = t.replace(hindi, ' ' + roman + ' ')
    t = ' '.join(t.split())
    t = re.sub(r"\bhata(?:o|do)?\b", "hata", t)
    t = re.sub(r"\bnikal(?:o|do)?\b", "nikal", t)
    subtitle_option = _subtitle_option(t)
    independent = [bool(re.search(pattern, t)) for pattern in (
        r"\b(?:undo|restore|wapas|वापस)\b|rehne de|रहने दे",
        r"\b(?:export|render|एक्सपोर्ट)\b|save edited|final video",
        r"\b(?:approve|confirm)\b", r"clear edits|reset edits")]
    # Multiple independent mutations need separate explicit requests. Never silently
    # run just one half of 'approve and export' or 'undo and clear edits'.
    if sum(independent) > 1:
        return "unknown", {"heard": text}
    if re.fullmatch(r"(?:undo|restore|wapas|वापस)(?: (?:kar|karo|karna|do|last|edit|cut|operation|it))*", t) or re.search(r"rehne de|रहने दे", t):
        return "undo", {}
    if re.fullmatch(r'(?:recording (?:i want to )?)?(?:shoot|record|make) (?:a )?(?:quick |short )?(?:reel|video)', t):
        return 'record_start', {}
    if re.search(r"\b(?:record|recording|रिकॉर्डिंग)\b", t):
        for action, pattern in (("stop", r"stop|band|bandh|बंद"), ("resume", r"resume|continue|जारी"),
                                ("pause", r"pause|rok|रोक"), ("start", r"start|shuru|शुरू|open")):
            prefix = r'(?:camera (?:open kar|kholo) (?:aur|and) )?' if action == 'start' else ''
            request = prefix + r'(?:(?:' + pattern + r') (?:the )?(?:record|recording)|(?:record|recording) (?:' + pattern + r'))(?: (?:kar|karo|karna|do|de|now|please))*'
            if re.fullmatch(request, t):
                return "record_" + action, {}
    camera_request = r'(?:(?:open|launch|show|start) (?:the |my )?(?:camera|webcam)(?: app)?|(?:camera|webcam)(?: app)? (?:open|kholo|khol|chala)(?: (?:kar|karo|do|de|na))*)'
    polite_end = r'(?: (?:please|now|quick|quickly|fast|asap|for me))*'
    purpose = r'(?: (?:i want to|i need to|so i can) (?:take|click|get|see|check|make) (?:a |the |my )?(?:photo|picture|selfie|video|read|reel|preview|look))?'
    if re.fullmatch(camera_request + polite_end + purpose, t):
        return 'open_camera', {}
    if re.fullmatch(r'(?:कैमरा|कैमरे|वेबकैम)(?: ऐप)? (?:खोलो|खोल)(?: दो| दे)?|(?:खोलो|खोल) (?:कैमरा|वेबकैम)', t):
        return 'open_camera', {}
    pause = bool(re.search(r"\b(?:pauses?|silence|gaps?|खामोशी|विराम)\b", t))
    if pause and (independent[1] or independent[2] or independent[3]):
        return "unknown", {"heard": text}
    number_text = t
    numbers = {"zero": 0, "one": 1, "two": 2, "do": 2, "दो": 2, "three": 3, "teen": 3, "तीन": 3,
               "four": 4, "चार": 4, "five": 5, "पांच": 5, "पाँच": 5, "six": 6, "seven": 7,
               "eight": 8, "nine": 9, "ten": 10, "एक": 1}
    words = "|".join(numbers)
    number_text = re.sub(rf"\b({words}) point ({words})\b", lambda m: f"{numbers[m[1]]}.{numbers[m[2]]}", number_text)
    number_text = re.sub(rf"(?<!\w)({words})(?=\s+(?:seconds?|secs?|milliseconds?|ms|minutes?|mins?)(?!\w))",
                         lambda m: str(numbers[m[1]]), number_text)
    quantities = list(re.finditer(r"(?<![\w.+\-])([+\-]?(?:\d+(?:\.\d+)?|\.\d+))\s*(milliseconds?|ms|seconds?|secs?|minutes?|mins?)(?!\w)", number_text))
    if len(quantities) > 1 or (pause and re.search(r"\b(?:below|under|shorter|less than|or|ya)\b", t)):
        return "unknown", {"heard": text}
    seconds = None
    if quantities:
        quantity = quantities[0]
        if pause and re.search(r"\d", number_text[:quantity.start()] + number_text[quantity.end():]):
            return "unknown", {"heard": text}
        seconds = float(quantity[1]) * (.001 if quantity[2].startswith("milli") or quantity[2] == "ms" else 60 if quantity[2].startswith("min") else 1)
    elif pause and re.search(r"\d|\b(?:over|longer than|threshold|milliseconds?|seconds?|minutes?|half|quarter|point)\b", number_text):
        # Never replace an unparsed explicit duration with the default threshold.
        return "unknown", {"heard": text}
    preferences = bool(re.search(r"\b(?:preferences?|settings|सेटिंग)\b", t))
    if preferences and re.search(r"\b(?:delete|forget|bhool|remove|hata)\b", t):
        if re.search(r"\b(?:and|aur|then|phir)\b|और|फिर", t) or (pause and subtitle_option is not None):
            return "unknown", {"heard": text, "reason": "Delete each preference separately; no editing instruction was executed."}
        if pause:
            return "delete_preference", {"key": "pause_threshold"}
        if subtitle_option is not None:
            return "delete_preference", {"key": "burn_subtitles"}
        return "unknown", {"heard": text, "reason": "Specify which preference to forget: pause threshold or subtitles."}
    explicit_memory = bool(re.search(r"\b(?:always|remember|hamesha|हमेशा|याद)\b|agli baar|अगली बार", t))
    if explicit_memory and subtitle_option is not None and not pause:
        return "save_preference", {"key": "burn_subtitles", "value": subtitle_option}
    if explicit_memory and (pause or "same settings" in t or "same setting" in t):
        args = {"seconds": seconds} if seconds is not None else {}
        if subtitle_option is not None:
            args["subtitles"] = subtitle_option
        return "save_preference", args
    if re.search(r"\b(?:preferences?|settings)\b", t) and re.search(r"\b(?:show|list|dikha|दिखा)\b", t):
        return "preferences", {}
    if re.fullmatch(r"(?:(?:please|haan|yes|okay) )?(?:approve|confirm)(?: (?:all|these|the|suggested|cuts?|edits?))*", t) or t == "मंजूर":
        return "approve", {}
    if re.fullmatch(r"(?:clear|reset) (?:all )?edits(?: now)?", t):
        return "clear", {}
    export = bool(re.match(r"(?:(?:ab|now) )?(?:export|render|एक्सपोर्ट|save edited|final video)\b", t) or
                  re.match(r"(?:is|iss|iski|iske|isski|isske|ye|yeh|this|current|edited|video|the video)\b.*\b(?:export|render)\b", t))
    if export:
        if pause or re.search(r"\b(?:transcribe|undo|approve|clear)\b", t):
            return "unknown", {"heard": text}
        return "export", {"subtitles": subtitle_option} if subtitle_option is not None else {}
    if subtitle_option is not None and not pause and re.match(r"(?:remove|disable|turn off|hata|nikal|subtitles? (?:remove|disable|hata|nikal))\b", t):
        return "set_subtitles", {"enabled": False}
    transcribe_request = bool(re.match(r"(?:(?:ab|now) )?(?:transcribe|transcript|subtitles?|सबटाइटल)\b", t) or
                              re.match(r"(?:add|generate|create|enable) subtitles?\b", t) or re.search(r"सुनकर लिख|likh ke", t))
    if transcribe_request and not pause:
        return "transcribe", {"subtitles": subtitle_option} if subtitle_option is not None else {}
    pause_request = bool(re.match(r"(?:remove|detect|find|clean|set|hata|nikal|ab|now|is|iss|iski|iske|isski|isske|ye|yeh|this|current|mere|meri|mujhe|jitne|unnecessary|long|all|video|pauses?|silence|gaps?)\b|इस|ये|यह", t))
    if pause and pause_request and re.search(r"\b(?:remove|detect|find|hata|हटा|हटाओ|काट|clean|nikal|निकाल|set|रिमूव)\b", t):
        if re.search(rf"\b(?:first|last|previous|next|middle|second|third)\s+(?:(?:\d+|{words})\s+)?(?:pauses?|gaps?|silence)\b", t):
            return "unknown", {"heard": text, "reason": "A particular pause needs a selected cut or explicit source boundaries; no edits were made."}
        takes = bool(re.search(r"\b(?:takes?|retakes?|attempts?|टेक)\b", t))
        last_take = takes and bool(re.search(r"\b(?:last|latest)\b", t)) and bool(re.search(r"\b(?:keep|rakh|rakhna|rakho|रखना|रख)\b", t))
        detect_retakes = takes and bool(re.search(r"\b(?:detect|find|identify|review)\s+(?:the\s+)?retakes?\b", t))
        if takes and not last_take and not detect_retakes:
            return "unknown", {"heard": text, "reason": "That take selection is unsupported. Use explicit source boundaries or request retake suggestions; no edits were made."}
        args = {"seconds": seconds} if seconds is not None else {}
        if last_take:
            args["keep_last"] = True
        elif detect_retakes:
            args["detect_retakes"] = True
        if subtitle_option is not None:
            args["subtitles"] = subtitle_option
        return "analyse", args
    if re.search(r"\b(?:retakes?|takes?)\b", t) and re.search(r"\b(?:last|latest|detect|find|आखिरी)\b", t):
        return "retakes", {"keep_last": "last" in t or "latest" in t}
    if re.search(r"cut that|cut previous|pichla.*(?:cut|hata)|पिछला.*(?:काट|हटा)", t):
        return "cut_previous", {}
    if "original" in t and re.search(r"\b(?:save|keep|rakh|रख)\b", t):
        return "preserve_original", {}
    return "unknown", {"heard": text}
