from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Use your exact model tags from ollama list
llm_fast = OllamaLLM(model="merid-interface:latest")   # gemma-based fast
llm_deep = OllamaLLM(model="merid-strategist:latest")  # llama3-based deep

# Simple prompt template
template = """
You are a precise crypto market analyst.
Current date: 2026-01-08

Question: {question}

Answer concisely in 3-5 sentences. Include your confidence level.
"""

prompt = ChatPromptTemplate.from_template(template)
chain = prompt | llm_deep | StrOutputParser()

# Test it
question = "BTC just broke $105,000 with record volume on Binance. Is this sustainable or a blow-off top?"

print("Question:", question)
print("\nResponse:")
response = chain.invoke({"question": question})
print(response)
