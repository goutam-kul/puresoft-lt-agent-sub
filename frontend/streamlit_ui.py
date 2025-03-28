import streamlit as st
import requests
import json
import os

API_BASE_URL = "http://127.0.0.1:8000"

st.set_page_config(
    page_title="Assistant",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.title("Meet Dex! Your Language Assistant")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = None

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Hey! I want to learn a new language."):
    # Display user message in container
    with st.chat_message("user"):
        st.markdown(prompt)
    # Add user message to session history
    st.session_state.messages.append({"role": "user", "content":  prompt})

    payload = {
        "query": prompt,
        "session_id": st.session_state.session_id  # Get ID from streamlit state
    }
    try:
        # Make the API call
        response = requests.post(
            url=f"{API_BASE_URL}/chat",
            json=payload
        )
        # Load json from response
        response_data = response.json()

        ai_response_text = response_data.get('response_str')
        backend_session_id = response_data.get('session_id')
        st.sidebar.write(ai_response_text)
        st.sidebar.write(backend_session_id)

        st.session_state.session_id = backend_session_id


        with st.chat_message("assistant"):
            st.markdown(ai_response_text)

        st.session_state.messages.append({"role": "assistant", "content": ai_response_text})

    except requests.exceptions.RequestException as e:
        st.error(f"Backend Error: {e}")
    except Exception as e:
        st.error(f"An error occured : {e}")