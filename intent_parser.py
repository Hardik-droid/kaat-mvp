"""Common desktop intents; the existing media parser remains a separate layer."""
import re

from tools.windows_apps import WEBSITES, canonical_name


def normalize_request(text):
    text = re.sub(r'^(?:(?:hey|hello|hi|ok)\s*[,.!]?\s*)+', '', text, flags=re.I)
    text = re.sub(r'^(?:whisper|visper|whisp|kaat|caught|काट|विस्पर)\b[\s,.!]*', '', text, flags=re.I)
    text = re.sub(r'^(?:(?:i want you to|i want to|can you|could you|please|just|zara|bas|ab|mujhe|bhai|whisper|kaat)\s+)+', '', text, flags=re.I)
    # A language declaration changes how the user will speak, not the action.
    text = re.sub(r'[.?!,]?\s*(?:main hindi (?:mein|me|men) bolunga|i (?:will|ll) speak (?:in )?hindi)[.?!]*$', '', text, flags=re.I)
    return text.strip(' .!?')


def parse_recording_request(text):
    """Normalize a Camera qualifier without inventing a missing recording verb."""
    t = text
    for hindi, roman in (('रिकॉर्डिंग', 'recording'), ('रिकार्डिंग', 'recording'),
                         ('कैमरा', 'camera'), ('कैमरे', 'camera'), ('ऐप', 'app'),
                         ('शुरू', 'start'), ('बंद', 'band'), ('रोको', 'pause'),
                         ('रोक', 'pause'), ('जारी', 'resume'), ('में', 'mein'),
                         ('से', 'se'), ('पर', 'par'), ('करो', 'karo'), ('कर', 'kar'),
                         ('दो', 'do'), ('दे', 'de')):
        t = t.replace(hindi, ' ' + roman + ' ')
    t = ' '.join(t.split())
    if not re.search(r'\brecord(?:ing)?\b', t):
        return None
    camera = r'(?:the |my )?(?:windows )?(?:camera|webcam)(?: app)?'
    if re.fullmatch(r'(?:but )?recording (?:from|in|using|with) ' + camera, t) or re.fullmatch(camera + r' (?:se|mein|me|par) recording', t):
        return 'clarify_recording', {
            'reason': 'Did you mean start recording in Windows Camera? No recording action was taken.',
            'suggested_command': 'Start recording from the camera app.'}
    t = re.sub(r'\b(?:from|in|using|with|on) ' + camera + r'\b', ' ', t)
    t = re.sub(r'\b' + camera + r' (?:se|mein|me|par)\b', ' ', t)
    t = re.sub(r'^' + camera + r' (?=record(?:ing)?\b)', '', t)
    t = ' '.join(t.split())
    tail = r'(?: (?:kar|karo|karna|do|de|now|please|for me))*'
    recording = r'(?:record|recording)(?: (?:a |the )?video)?'
    for action, verbs in (('start', 'start|begin|shuru'), ('stop', 'stop|end|finish|band|bandh'),
                          ('pause', 'pause|rok'), ('resume', 'resume|continue|jari')):
        if re.fullmatch(r'(?:(?:' + verbs + r') (?:the )?' + recording +
                        r'|' + recording + r' (?:' + verbs + r'))' + tail, t):
            return 'record_' + action, {}
    return None


def parse_common(text, original=''):
    t = normalize_request(text)
    if re.fullmatch(r'(?:help|show help|what can you do|commands|what can whisper do|features)', t):
        return 'help', {}
    if re.fullmatch(r'(?:cancel|cancel command|stop listening|never mind)', t):
        return 'cancel', {}
    if re.fullmatch(r'(?:give (?:the |a )?presentation|start (?:the )?presentation|presentation|introduce yourself|apna intro do|give demo|start demo|demo|present yourself)', t) or re.search(r'\b(?:give|start|do)\s+(?:the\s+)?presentation\b', t):
        return 'presentation', {}
    if re.fullmatch(r'(?:who are you|what is your name|tum kaun ho|who made you|who created you)', t):
        return 'identity', {}
    if re.fullmatch(r'(?:what(?: is| s)?(?: the)? time(?: is it)?|what time(?: is it)?|current time|time kya (?:hai|hua hai))', t):
        return 'system_time', {}
    if re.fullmatch(r'(?:what(?: is| s)?(?: today s| the)? date|current date|today s date|aaj kya date hai|aaj ki date)', t):
        return 'system_date', {}
    if re.fullmatch(r'(?:tell (?:me )?a joke|joke sunao|say a joke|make me laugh|koi joke)', t):
        return 'joke', {}
    if re.fullmatch(r'(?:how are you|kaise ho|sab theek|are you there|are you listening)', t):
        return 'status_check', {}
    if re.fullmatch(r'(?:volume up|increase volume|louder|volume badhao|awaaz badhao)', t):
        return 'system_volume_up', {}
    if re.fullmatch(r'(?:volume down|decrease volume|quieter|volume kam karo|awaaz kam karo)', t):
        return 'system_volume_down', {}
    if re.fullmatch(r'(?:mute|unmute|mute volume|awaaz band|mute karo)', t):
        return 'system_mute', {}
    if re.fullmatch(r'(?:take (?:a )?screenshot|screenshot lo|capture screen|screenshot)', t):
        return 'system_screenshot', {}
    if re.fullmatch(r'(?:minimize(?: all)?|show desktop|desktop dikhao)', t):
        return 'system_minimize', {}
    recording = parse_recording_request(t)
    if recording:
        return recording
    if re.search(r'\bfillers?\b', t) and re.search(r'\b(?:remove|detect|find|hata|hatao|nikal|clean)\b', t):
        if re.search(r'\b(?:export|approve|undo|delete|open|record(?:ing)?|forget)\b', t):
            return 'unknown', {'reason':'Detect fillers first, review the proposed cuts, then export separately.'}
        return ('speech_cleanup' if re.search(r'\b(?:pauses?|silence)\b', t) else 'fillers'), {}
    if re.fullmatch(r'(?:clean|clean up)(?: this| the| my)? video|(?:is |ye )?video (?:clean|cleanup) kar(?: do| de)?', t):
        return 'speech_cleanup', {}
    owned = (r'(?:(?:(?:all|the|those|these|all those|all the|all these) )?'
             r'(?:apps|applications|windows|stuff|things|everything)(?: (?:that|which))?'
             r' you (?:have |just |recently )*opened|(?:what|whatever|all) you (?:have |just |recently )*opened)'
             r'(?: recently| just now| for me)?')
    hinglish = (r'(?:jo (?:apps |windows |cheezein )?tumne (?:abhi )?khol(?:e|a)(?: hain| hai| the)?'
                r'|tumne jo (?:apps |windows |cheezein )?khol(?:e|a)(?: hain| hai| the)?)'
                r' (?:unko|unhe|woh sab|wo sab|sab) band (?:kar|karo)(?: do| de)?')
    if re.fullmatch(r'(?:close|shut)(?: down)? '+owned, t) or re.fullmatch(hinglish, t):
        return 'close_recent', {}
    if re.fullmatch(r'(?:close|shut)(?: down)? (?:all|everything)(?: apps| applications| windows)?', t):
        return 'clarify_close', {'reason':'Say “close the apps you opened” to close only windows opened by Whisper.'}
    if re.fullmatch(r'(?:close|shut)(?: down)? (?:this|current|active)(?: window| app| application)?|(?:isse|ise) band (?:kar|karo)(?: do| de)?', t):
        return 'close_active_window', {}
    close_app = re.fullmatch(r'(?:close|shut)(?: down)?\s+([a-zA-Z0-9\s]+?)(?: app| application)?', t)
    if close_app:
        app_target = close_app[1].strip()
        if app_target not in ('all', 'everything', 'all apps', 'all windows'):
            return 'close_application', {'application': canonical_name(app_target)}
    close_app_hi = re.fullmatch(r'([a-zA-Z0-9\s]+?)\s+(?:band|shut|close) (?:kar|karo)(?: do| de)?', t)
    if close_app_hi:
        app_target = close_app_hi[1].strip()
        if app_target not in ('all', 'everything', 'woh sab', 'wo sab', 'sab'):
            return 'close_application', {'application': canonical_name(app_target)}
    yt_match = re.fullmatch(r'(?:play|chalao)\s+(.+?)(?:\s+(?:on|in)\s+youtube)?', t) or re.fullmatch(r'youtube (?:pe|par)\s+(.+?)\s+(?:chalao|play karo|search karo)', t)
    if yt_match and not re.search(r'\b(?:video|recording|reel|cut|khol|open)\b', yt_match[1]):
        return 'youtube_play', {'query': yt_match[1].strip()}
    yt_search = re.fullmatch(r'search\s+(.+?)\s+(?:on|in)\s+youtube', t)
    if yt_search:
        return 'youtube_play', {'query': yt_search[1].strip()}
    if not re.search(r'\b(?:khol|open|chala|launch)\b', t):
        google_match = (re.fullmatch(r'search\s+(?:for\s+)?(.+?)(?:\s+(?:on|in)\s+google)?', t)
                        or re.fullmatch(r'google search\s+(.+)', t)
                        or re.fullmatch(r'(.+?)\s+(?:search karo|google karo)', t))
        if google_match and not re.search(r'\b(?:video|camera|recording|subtitles?|pauses?)\b', google_match[1]):
            return 'web_search', {'query': google_match[1].strip()}
    if re.fullmatch(r'(?:list|show)(?: installed| available)? (?:apps|applications)', t):
        return 'list_applications', {}
    if re.fullmatch(r'(?:get|show)(?: the)? (?:active|current) (?:app|application|window)', t):
        return 'get_active_application', {}
    if re.fullmatch(r'(?:show|list|get)(?: my| saved)? (?:preferences|settings)', t):
        return 'preferences', {}
    if re.fullmatch(r'(?:remember|save)(?: my| these| current| same)? settings', t):
        return 'save_preference', {'all_settings': True}
    if re.fullmatch(r'(?:remember|always)(?: to)? (?:save|preserve|keep)(?: my| the)? original(?: videos?)?', t):
        return 'save_preference', {'key':'preserve_original','value':True}
    if re.fullmatch(r'(?:pichla|last|previous) (?:cut|edit) undo(?: kar| karo| do)?', t):
        return 'undo', {}
    if re.fullmatch(r'(?:pause|pause kar|pause karo)',t):return 'record_pause',{}
    if re.fullmatch(r'(?:resume|resume kar|resume karo)',t):return 'record_resume',{}
    if re.fullmatch(r'(?:start|begin)(?: the)? recording(?: (?:a )?few seconds(?: of)? (?:a )?reel)?', t):
        return 'record_start', {}
    source = re.match(r'^(?:select|choose|open) (?:the |my )?video(?:\s+(.+))?$', normalize_request(original), re.I)
    if source:
        return 'select_video', {'source':source[1].strip('"\'')} if source[1] else {}
    if re.fullmatch(r'(?:analyse|analyze|inspect)(?: the| my)? video',t):return 'inspect_video',{}
    if re.search(r'\b(?:and|aur|then|phir|also)\b',t):
        return None  # Existing media rules can handle their explicitly supported combinations.
    target = None
    match = re.fullmatch(r'(?:open|launch|show|start)\s+(.+)',t)
    if match:target=match[1]
    if target is None:
        match=re.fullmatch(r'(.+?)\s+(?:khol(?:o|na)?|open|chala(?:o)?|खोलो|खोल|चलाओ)(?:\s+(?:kar|karo|karna|de|do|ke|dikha|दो|दे|please))*',t)
        if match:target=match[1]
    if target is None:return None
    if re.search(r'\b(?:record|recording|pauses?|retakes?|subtitles?|settings|preferences)\b', target):
        return None
    target=re.sub(r'^(?:my|mera|meri|the)\s+','',target)
    target=re.sub(r'\s+(?:please|now|for me)$','',target)
    if target.casefold().startswith(('camera','webcam','windows camera','कैमरा')):
        return None  # Preserve the existing camera intent and its consent guard.
    url=re.search(r'https?://[^\s]+',original,re.I)
    if url:return 'open_website',{'url':url[0].rstrip('.,!?')}
    path=re.search(r'[A-Za-z]:[\\/].+',original)
    if path:
        return 'open_folder',{'path':path[0].strip('"\' .')}
    name=canonical_name(target)
    if name in WEBSITES:return 'open_website',{'url':WEBSITES[name]}
    folder=re.sub(r'\s+folder$','',name)
    if folder in ('downloads','desktop','documents','home'):
        return 'open_folder',{'path':folder}
    return 'open_application',{'application':name}
