#!/usr/bin/env python3
"""
Simple script to send requests to Google Gemini API
"""

import os
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables from .env file
load_dotenv()

# Configure the Gemini API
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
        # Get user input
        user_input = input("\nYou: ").strip()

        # Check for exit commands
        if user_input.lower() in ['exit', 'quit']:
            print("\nGoodbye!")
            break

        # Skip empty inputs
        if not user_input:
            continue

        # Send request to Gemini
        response = model.generate_content(user_input)
        print(f"\nGemini: {response.text}")

    except KeyboardInterrupt:
        print("\n\nGoodbye!")
        break
    except Exception as e:
        print(f"\nError: {e}")
