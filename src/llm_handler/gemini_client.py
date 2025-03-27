from typing import List, Dict, Any, Optional
from google import genai
from google.genai import types
from src.config.settings import settings
from langchain_community.chat_message_histories import SQLChatMessageHistory
from loguru import logger
import sqlite3
from pydantic import BaseModel
import re
import datetime
import uuid


class Assistant:
    """Base class for all LLM calls"""

    def __init__(self, session_id: str):
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self.gemini_model = settings.GEMINI_MODEL
        self.chat_message_history = SQLChatMessageHistory(
            session_id=session_id,
            connection="sqlite:///sqlite.db"
        )

    def _detect_intention(
        self, 
        query: str, 
    ) -> str:
        # Define keywords for trigger
        keywords = ['mistakes', 'mistake', 'error', 'errors', 'wrong', 'review', 'summary', 'correct', 'feedback']

        try:
            # If no keywords found the intent is GENERAL_CHAT
            if not any(word in keywords for word in query.split()):
                logger.info("GENERAL CHAT intent")
                return "GENERAL_CHAT"
            else: # If keyword foudn send intent detection request
                intent = self.client.models.generate_content(
                    model=self.gemini_model,
                    contents=query,
                    config=types.GenerateContentConfig(
                        temperature=0,
                        system_instruction=settings.INTENT_DETECTION_PROMPT.format(query=query),
                        candidate_count=1
                    )
                )
            try:
                # Check of response type
                if isinstance(intent, types.GenerateContentResponse):
                    return intent.text
            except TypeError as e:
                logger.error(f"Respons type not correct: {e}")

        except Exception as e:
            logger.error(f"Failed to send request to Gemini: {e}")

    def ask(
        self, 
        query: str,
        system_prompt: str = settings.SYSTEM_PROMPT, 
        review_mistakes_prompt: str = settings.REVIEW_MISTAKE_PROMPT
    ) -> str:
        """Base method for all operations"""
        logger.info("Detecting user intention")
        # First find intent of the user
        # try:
        intent = self._detect_intention(query=query)
        intent = intent.strip()
        logger.info(f"Detected Intent: {intent}")
        # except Exception as e:
        #     logger.error(f"Intent Detection failed {e}")
        #     intent = "DETECTION_ERROR"

        add_to_history = True
        
        if intent in ["SESSION_MISTAKES", "ALL_MISTAKES", "UNCLEAR_MISTAKES"]:
            logger.info(f"Handling mistake review intent: {intent}")
            mistakes_data = None
            no_mistakes_message = ""

            # ---1. Retrieve mistakes and store in mistakes_data variable
            try: 
                if intent == "SESSION_MISTAKES" or intent == "UNCLEAR_MISTAKES":
                    mistakes_data = self._get_mistakes_from_current_session(session_id=self.chat_message_history.session_id)
                    no_mistakes_message = "It looks like you haven't made any mistakes during this session."
                elif intent == "ALL_MISTAKES":
                    mistakes_data = self._get_all_mistakes()
                    no_mistakes_message = "Wow! It looks like you have not made any mistakes across all sessions."
                
                # ---2. Handle DB errors or No mistakes ---
                if isinstance(mistakes_data, dict) and 'error' in mistakes_data.get('status', ''):
                    logger.error(f"Error during mistakes data retrieval from database: {e}")
                    final_response_str = "Sorry, I encountered and error during retrieving your mistakes data from the database."

                    add_to_history = False # Don't add to message if DB failed
                elif not mistakes_data:
                    logger.info("NO mistakes found in the database.")
                    final_response_str = no_mistakes_message
                    add_to_history = False  # Log this query in the chat history
                
                else:
                    # ---3. Parse mistakes data ---
                    parsed_mistakes_str = self._parse_mistakes_data(mistakes_data=mistakes_data)
                    if not parsed_mistakes_str:
                        logger.warning("Mistakes data exists but parsed string is empty.")
                        final_response_str = no_mistakes_message
                    else:
                        # ---4. Call LLM for review
                        logger.info("Calling LLM to review mistakes")
                        try:
                            formatted_mistake_review_prompt = review_mistakes_prompt.format(
                                parsed_mistakes_string=parsed_mistakes_str,
                                query=query
                            )
                            review_response = self.client.models.generate_content(
                                model=self.gemini_model,
                                contents=query,
                                config=types.GenerateContentConfig(
                                    temperature=1.0,
                                    system_instruction=[formatted_mistake_review_prompt]
                                ),
                            )
                            final_response_str = review_response.text
                            logger.info("LLM review generated successfully")
                            add_to_history = False # Not gonna add mistake reviews in chat history
                        except Exception as e:
                            logger.error(f"Error during LLM call: {e}")

            except Exception as e:
                logger.error(f"Unexpected error during Mistake review handling: {e}")
                final_response_str = "An unexpected error occurred while processing your mistake review request."
                add_to_history = False # Avoid logging

        elif intent == "NOT_MISTAKES" or intent == "GENERAL_CHAT":
            logger.info("Handling general chat query")
            try:
                # --- Standard Chat flow ---
                chat_context = self.build_context_with_chat()
                chat_response = self.client.models.generate_content(
                    model=self.gemini_model,
                    contents=chat_context + query,
                    config=types.GenerateContentConfig(
                        temperature=0.9,
                        system_instruction=system_prompt,
                    ),
                )

                chat_response_text = chat_response.text

                # --- Mistake Logging ---
                mistakes_found = self._parse_and_log_mistakes(response_text=chat_response_text, session_id=self.chat_message_history.session_id)
                if mistakes_found:
                    logger.info(f"Logged {len(mistakes_found)} mistakes during current session.")

                    final_response_str = self._clean_mistake_tags(chat_response_text)
                else:
                    final_response_str = chat_response_text
                
                add_to_history = True

            except Exception as e:
                logger.error(f"Failed to sent request to gemini: {e}")
                final_response_str = "Sorry, I encoutered an error while processing your message."
                # Don't add to history
                add_to_history = False

        else: # Detect any other errors from intent
            logger.warning(f"Unhandled or error in intent detection: {intent}")
            final_response_str = "Sorry! I am not sure how to handle this request."
            # Don't need to add this response
            add_to_history = False

        # Add to chat history if all checks pass
        if add_to_history:
            try:
                logger.info("Chat added to history")
                self.chat_message_history.add_user_message(message=query)
                self.chat_message_history.add_ai_message(message=final_response_str)
            except Exception as e:
                logger.error(f"Failed to add messages to chat history: {e}")

        return final_response_str
    

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
        
        logger.info(f"Context query built")
        return context_query
    
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

            # Get current time of timestamp field in db
            local_time = datetime.datetime.now()

            # Convert to string 
            timestamp_str = local_time.isoformat(sep=' ', timespec='seconds') # e.g., '2025-03-27 09:39:50'

            # Ensure the table exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mistakes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    user_input_snippet TEXT,
                    correction TEXT,
                    mistake_type TEXT,
                    explanation TEXT 
                );
            """)

            cursor.execute("""
                INSERT INTO mistakes (session_id, timestamp, user_input_snippet, correction, mistake_type, explanation) 
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                mistake_data.get("session_id"),
                timestamp_str,
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
            conn.rollback()
        finally:
            if conn: 
                conn.close()

    def _clean_mistake_tags(self, text: str) -> str:
        pattern = re.compile(r"\[CorrectionStart\].*?\[CorrectionEnd\]", re.DOTALL)
        # Remove the matched content  from the response
        return pattern.sub("", text).strip('')
    
    def _parse_mistakes_data(self, mistakes_data: List[Dict]) -> str:
        """Parse the mistakes data list of dictioonary and return a sophisticated string"""
        logger.info("Parsing the mistakes data")
        mistake_string = ""
        if isinstance(mistakes_data, list): 
            for i, mistake in enumerate(mistakes_data):
                mistake_string += "`[MistakesStart]`"
                mistake_string += f"Mistake - {i + 1}. | "
                mistake_string += f"Your Input - {mistake.get('user_input_snippet')} | "
                mistake_string += f"Correct Response - {mistake.get('correction')} | "
                mistake_string += f"Mistake Type - {mistake.get('mistake_type')} | "
                mistake_string += f"Explanation - {mistake.get('explanation')} | "
                mistake_string += "`[MistakesEnd]`"

        return mistake_string.strip()
       
    def _get_all_mistakes(self, ):
        """Get all the mistakes in the database"""
        logger.info("Extracting all rows from database")
        try:
            conn = sqlite3.connect("sqlite.db")

            # Enable row factory to get the column names 
            conn.row_factory = sqlite3.Row

            cursor = conn.cursor()
            # Query the database
            cursor.execute("SELECT * FROM mistakes;")
            # Fetch all results as sqlite3.Row objects
            rows = cursor.fetchall()

            logger.info("Rows Extracted")

            # Convert row to a list of dicts with column names
            mistakes = [dict(row) for row in rows]

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return {
                "status":f"error: {e}"
            }
        finally:
            if conn:
                conn.close()

        return mistakes

    def _get_mistakes_from_current_session(self, session_id: str):
        """Get tuples from database where session_id matches"""
        logger.info("Extracting rows based on session_id from mistakes table.")
        try: 
            conn = sqlite3.connect("sqlite.db")
            
            # Enable row factory 
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Extract row based on session_id
            cursor.execute("SELECT * FROM mistakes WHERE session_id = ?", (session_id, ))
            # Fetch all results 
            rows = cursor.fetchall()

            # Iterate to get
            session_mistakes = [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Failed to extracted from database: {e}")
            return {
                "status": f"error{e}"
            }
        finally:
            if conn:
                conn.close()
        
        return session_mistakes


if __name__ == "__main__":
    current_session_id = str(uuid.uuid4())
    assist = Assistant(session_id=current_session_id)
    while True:
        query = input(": ")
        if query == 'bye':
            break
        else:
            response = assist.ask(query=query)
            print(response)
        
    # intent = assist._detect_intention(query="Show me the mistakes I have made during this chat ")
    # print(intent)