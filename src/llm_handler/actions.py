from typing import List, Dict, Any

accepted_languages = ['hindi', 'english', 'spanish', 'japnese', 'italian', 'spanish', 'mandarin', 'russian'
                      ]
levels = ['beginner', 'intermediate', 'advanced']

def greet() -> Dict[str, str]:
    """Greet the user"""

    return {
        "response": "Hello what language would you like to learn today?"
    }

def set_language(context: str) -> Dict[str, Any]:
    """Get the language the user want to learn"""

    text = context.lower().split()
    for lang in text:
        if lang in accepted_languages:
            selected_language = lang
    return {
        "response": f"Sure I can help you learn {selected_language}."
    }

def ask_current_level() -> Dict[str, str]:
    """Ask the current level of understanding of the user's selected language"""

    return {
        "response": "But, before we move forward, can you tell me you current level of understanding between beginner, intermediate or advanced"
    }

def set_current_level(context: str) -> Dict[str, Any]:
    """Get the current level of understanding of user from user's reply"""
    
    text = context.lower().split()
    for level in text:
        if level in levels:
            current_level = level
    return {
        "response": f"Great! I'll create a {current_level} level exercise for you."
    }


# import time
# language = input(f"{greet().get('response')}:")
# time.sleep(1)
# print(set_language(context=language).get('response'))
# time.sleep(1)
# current_level = input(f"{ask_current_level().get('response')}:")
# time.sleep(1)
# print(set_current_level(context=current_level).get('response'))