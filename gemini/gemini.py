#!/usr/bin/env python3
"""
Simple script to send requests to Google Gemini API
"""

import os
import sys
from dotenv import load_dotenv
from google import genai
from google.genai import types


load_dotenv()

api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
    raise ValueError("GEMINI_API_KEY not found in .env file")

client = genai.Client(api_key=api_key)
MODEL_ID='gemini-2.5-flash-lite' # gemini-3-flash-preview

LONG_PROMPT = """
        # Role: CLI Technical Architect (In-Depth Mode)
        ## Response Guidelines:
        - **Structure:** Use '##' for main sections and '---' for visual breaks.
        - **Tone:** Technical, thorough, and precise. Avoid conversational filler.
        - **Formatting:** - Use **bolding** for critical commands and parameters.
            - Use code blocks for all multi-line scripts or configuration files.
            - Organize complex processes into numbered steps (1., 2., 3.).
        - **Detail Level:** Provide comprehensive explanations, potential edge cases, and best practices.
        - **Terminal Optimization:** Avoid wide tables or long paragraphs. Use bulleted lists to keep the right margin clear.
        """
SHORT_PROMPT = """
        You are a concise technical CLI assistant.

        Rules:
        - Max 75 words.
        - Prioritize commands and code blocks.
        - Avoid long prose.
        - Avoid tables to prevent terminal wrapping issues
        - Prioritize code blocks for technical solutions
        """

is_long = len(sys.argv) > 1 and sys.argv[1] == "--long"
system_instruction = LONG_PROMPT if is_long else SHORT_PROMPT

chat = client.chats.create(
    model=MODEL_ID,
    config=types.GenerateContentConfig(
        #thinking_config=types.ThinkingConfig(thinking_level="low"),
        system_instruction=system_instruction,
        temperature=0.7,
    )
)

print(f"Gemini CLI ({'Long' if is_long else 'Short'} Mode) - Type 'exit' to quit\n")
print("-" * 50)

while True:
    try:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in ['exit', 'quit']:
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        response = chat.send_message(user_input)

        print(f"\nGemini: {response.text}")

    except KeyboardInterrupt:
        print("\n\nGoodbye!")
        break
    except Exception as e:
        print(f"\nError: {e}")
        if "429" in str(e):
            print("Free Tier Limit Reached Try again in a minute")
