from typing import List, Dict, Any, Optional
from google import genai
from google.genai import types
from src.config.settings import settings
from langchain_community.chat_message_histories import SQLChatMessageHistory
from loguru import logger
import sqlite3
from pydantic import BaseModel
import re


class Assistant:
    """Base class for all LLM calls"""

    def __init__(self):
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self.gemini_model = settings.GEMINI_MODEL
        self.chat_message_history = SQLChatMessageHistory(
            session_id="test_session",
            connection="sqlite:///sqlite.db"
        )

    def ask_gemini(self, context_query: str, system_query: str = settings.SYSTEM_PROMPT):
        logger.info("Generating response from Gemini")
        chat_context = self.build_context_with_chat()
        response = self.client.models.generate_content(
            model=self.gemini_model,
            contents= chat_context + context_query,
            config=types.GenerateContentConfig(
                temperature=0.9, 
                system_instruction=system_query,
            )
        )

        llm_response_text = response.text

        # --- Mistake logging logic ---
        mistakes_found = self._parse_and_log_mistakes(llm_response_text, self.chat_message_history.session_id)
        if mistakes_found:
            logger.info(f"Logged {len(mistakes_found)} mistakes for session {self.chat_message_history.session_id}")

            # Clean the mistake Tags before savign the message
            cleaned_response_text = self._clean_mistake_tags(text=llm_response_text)
        else:
            cleaned_response_text = response.text

        # Add messages to database
        self.chat_message_history.add_user_message(message=context_query)
        self.chat_message_history.add_ai_message(message=cleaned_response_text)

        return response
    
    def _parse_and_log_mistakes(self, response_text: str, session_id: str) -> List[Dict]:
        """Parse LLM response for correction and logs them"""
        mistakes = []
        # Use Regex to find the correction format
        pattern = re.compile(r"\[CorrectionStart\](.*?)\[CorrectionEnd\]", re.DOTALL)

        for match in pattern.finditer(response_text):
            details_str = match.group(1).strip()
            mistake_data = {"session_id": session_id}

            # Simpel parsing based on | seperator
            parts = [p.strip() for p in details_str.split('|')]
            for part in parts:
                if part.lower().startswith("incorrect:"):
                    mistake_data['user_input_snippet'] = part[len("incorrect:") :].strip().strip('"')
                elif part.lower().startswith("correct"):
                    mistake_data['correction'] = part[len("correct:") :].strip().strip('"')
                elif part.lower().startswith("type"):
                    mistake_data['mistake_type'] = part[len("type:") :].strip().strip('"')
                elif part.lower().startswith("explanation"):
                    mistake_data['explanation'] = part[len("explanation:") :].strip().strip('"')
        
            if "user_input_snippet" in mistake_data and "correction" in mistake_data:
                mistakes.append(mistake_data)
                self._log_mistake_to_db(mistake_data)
            
        return mistakes

    def _log_mistake_to_db(self, mistake_data: Dict):
        """Insert a single mistake record in the database"""
        try:
            # First need to connect to the database
            conn = sqlite3.connect("sqlite.db")  
            cursor = conn.cursor()

            #TODO
            # Ensure the table exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mistakes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    user_input_snippet TEXT,
                    correction TEXT,
                    mistake_type TEXT,
                    explanation TEXT 
                );
            """)

            cursor.execute("""
                INSERT INTO mistakes (session_id, user_input_snippet, correction, mistake_type, explanation) 
                VALUES (?, ?, ?, ?, ?)
            """, (
                mistake_data.get("session_id"),
                mistake_data.get("user_input_snippet"),
                mistake_data.get("correction"),
                mistake_data.get("mistake_type"),
                mistake_data.get("explanation") 
                # Add other fields if extracted
            ))

            # Commit to database
            conn.commit()

        except sqlite3.Error as e:
            logger.error(f"Database error while logging mistake: {e}")
        finally:
            if conn: 
                conn.close()

    def build_context_with_chat(self, chat_history: SQLChatMessageHistory = None) -> str:
        """Convert Langchain chat message history to Human AI messages for LLM"""
        if chat_history is None:
            chat_history = self.chat_message_history
        
        # Get messages from chat history
        messages = chat_history.messages

        # Intialize context query
        context_query = ""

        # Iterate through messages and store human, ai message
        for chat in messages:
            if chat.__class__.__name__ == "HumanMessage":
                context_query += f"Human: {chat.content}"
            elif chat.__class__.__name__ == "AIMessage":
                context_query += f"\nAI: {chat.content}"
        
        logger.info(f"Context query built: {context_query}")
        return context_query

    def _clean_mistake_tags(self, text: str) -> str:
        pattern = re.compile(r"\[CorrectionStart\].*?\[CorrectionEnd\]", re.DOTALL)
        # Remove the matched content  from the response
        return pattern.sub("", text).strip()
       
    # def get_mistakes_by_session_id(self, session_id)




assist = Assistant()
first_response = assist.ask_gemini(context_query=f"Help me learn French langage, my current understanding level is beginner")
print(first_response.text)
while True:
    query = input(": ")
    if query != "q":
        response = assist.ask_gemini(context_query=query)
        print(response.text)
    else: 
        break

    