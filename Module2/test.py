from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace
from dotenv import load_dotenv
from langchain_community.document_loaders import UnstructuredPDFLoader
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate

llm = HuggingFaceEndpoint(
    repo_id="openai/gpt-oss-120b",
    task="text-generation"
)

model = ChatHuggingFace(llm=llm)
parser = JsonOutputParser()

loader = UnstructuredPDFLoader('table.pdf')

docs = loader.load()

prompt = PromptTemplate(
    template="Tell me  all the important lines \n {text} \n {format_inst}",
    input_variables=['text'],
    partial_variables={'format_inst' : parser.get_format_instructions()}
)

chain = prompt | model | parser

full_text = "\n".join(doc.page_content for doc in docs)

result = chain.invoke({'text' : full_text})

print(result)
