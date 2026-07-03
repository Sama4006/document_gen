"""LLM Service - Handles all OpenAI API interactions"""

from openai import OpenAI
from backend.config import settings
from typing import Optional


class LLMService:
    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model
    
    def generate_content(
        self,
        prompt: str,
        context: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1500
    ) -> str:
        """
        Generate content using OpenAI based on prompt and optional context
        
        Args:
            prompt: User prompt/request
            context: Retrieved context from RAG
            temperature: Creativity level (0-1)
            max_tokens: Max response length
            
        Returns:
            Generated content string
        """
        # Combine prompt with context if available
        full_prompt = prompt
        if context:
            full_prompt = f"""Context Information:
{context}

User Request:
{prompt}

Please generate content based on the context and request above."""
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional document generation assistant. Generate clear, well-structured content for Word documents."
                },
                {
                    "role": "user",
                    "content": full_prompt
                }
            ],
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        return response.choices[0].message.content
    
    def get_embedding(self, text: str) -> list:
        """
        Get embedding for text using OpenAI
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector
        """
        response = self.client.embeddings.create(
            model=settings.openai_embedding_model,
            input=text
        )
        return response.data[0].embedding


# Singleton instance
llm_service = LLMService()
