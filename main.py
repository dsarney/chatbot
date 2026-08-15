import os
import openai
from dotenv import load_dotenv

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")
model = os.getenv("OPENAI_MODEL", "gpt-5-nano")

if not openai.api_key:
    raise ValueError("OPENAI_API_KEY is not set")


def get_response(prompt):
    response = openai.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content.strip()


if __name__ == "__main__":
    while True:
        prompt = input("You: ")
        if prompt.lower() in ["exit", "quit", "bye"]:
            break

        response = get_response(prompt)
        print(f"Assistant: {response}")
