from huggingface_hub import InferenceClient
from dotenv import load_dotenv
import os

load_dotenv()
client = InferenceClient(token=os.getenv("HUGGINGFACEHUB_API_TOKEN"))

response = client.chat_completion(
    model="openai/gpt-oss-120b",
    messages=[{"role": "user", "content": "Say hello"}],
    max_tokens=20
)
print(response.choices[0].message.content)