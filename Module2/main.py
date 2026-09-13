from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace
from langchain_community.document_loaders import PyMuPDFLoader
from dotenv import load_dotenv
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from ocr import ocr_extract_pdf
from prompt import notice_extraction_prompt , parser

load_dotenv()

llm = HuggingFaceEndpoint(
    repo_id='openai/gpt-oss-120b',
    task="text-generation"
)

model = ChatHuggingFace(llm=llm)
parser = JsonOutputParser()


docs = ocr_extract_pdf('wbjee.pdf')

chain = notice_extraction_prompt | model | parser

result = chain.invoke({"text": docs})

print(result)