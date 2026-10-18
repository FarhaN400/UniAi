from langchain_ollama import ChatOllama

llm = ChatOllama(
    model="qwen3:4b-instruct",
    temperature=0,
    num_ctx=4096
)

response = llm.invoke(
    "What is the purpose of RAG in a university chatbot?"
)

print(response.content)