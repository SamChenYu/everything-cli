#!/usr/bin/env python3
"""
Deprecated! But for some reason 3x faster than the actual SDK.
"""

import os
from dotenv import load_dotenv
import google.generativeai as genai

CONVERSATION = """
        You are a concise technical CLI assistant.

        Rules:
        - Max 75 words.
        - Prioritize commands and code blocks.
        - Avoid long prose.
        - Avoid tables to prevent terminal wrapping issues
        - Prioritize code blocks for technical solutions
        """

load_dotenv()

api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
    raise ValueError("GEMINI_API_KEY not found in .env file")

genai.configure(api_key=api_key)

# Create the model
model = genai.GenerativeModel('gemini-3-flash-preview')

print("Gemini CLI - Type 'exit' or 'quit' to end the session\n")
print("-" * 50)

# Main loop
while True:
    try:
        user_input = input("\nYou: ").strip()

        if user_input.lower() in ['exit', 'quit']:
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        
        CONVERSATION += "\nUser:\n"
        CONVERSATION += user_input
        response = model.generate_content(CONVERSATION)
        CONVERSATION += "\nGEMINI:\n"
        CONVERSATION += response.text
        print(f"\nGemini: {response.text}")

    except KeyboardInterrupt:
        print("\n\nGoodbye!")
        break
    except Exception as e:
        print(f"\nError: {e}")