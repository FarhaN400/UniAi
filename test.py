import os
from dotenv import load_dotenv
from huggingface_hub import HfApi, InferenceClient

load_dotenv(override=True)

token = os.getenv("HUGGINGFACEHUB_API_TOKEN")

print("Account:", HfApi().whoami(token=token)["name"])

client = InferenceClient(token=token)

try:
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": "Hi"}],
        max_tokens=30
    )
    print(response.choices[0].message.content)
except Exception as e:
    print("Error type:", type(e).__name__)
    print("Error:", str(e))