import os
from dotenv import load_dotenv
from litellm import completion

load_dotenv()

def test_llm():
    # جرب النموذج الموجود في الإعدادات
    model = os.getenv("MODEL_NAME", "groq/llama-3.3-70b-versatile")
    print(f"🔍 Testing model: {model}")
    
    try:
        response = completion(
            model=model,
            messages=[{"role": "user", "content": "Say 'Hello!' in exactly 3 words."}],
            max_tokens=20
        )
        print("✅ Connection successful!")
        print(f"Response: {response.choices[0].message.content}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    test_llm()