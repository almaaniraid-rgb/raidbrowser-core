"""
LiteLLM Provider per RaidbrowsAI
Connette al freellmapi locale su http://127.0.0.1:31415
Supporta streaming e tool calling
"""
import json
import asyncio
from typing import AsyncGenerator, Optional, Dict, Any, List
from dataclasses import dataclass
import httpx


@dataclass
class ModelConfig:
    """Configurazione modello"""
    model: str = "auto"
    base_url: str = "http://127.0.0.1:31415"
    api_key: str = "freellmapi-36776e993a9163487ea2fbf90b7b3163283699a8546d550c"
    timeout: float = 300.0
    max_tokens: int = 4096
    temperature: float = 0.7


class LiteLLMProvider:
    """
    Provider async per LiteLLM/freellmapi locale
    Compatibile con OpenAI API (chat/completions, models)
    """
    
    def __init__(self, config: Optional[ModelConfig] = None):
        self.config = config or ModelConfig()
        self.client = httpx.AsyncClient(
            base_url=self.config.base_url,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json"
            },
            timeout=self.config.timeout
        )
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def list_models(self) -> List[Dict[str, Any]]:
        """Lista modelli disponibili"""
        response = await self.client.get("/v1/models")
        response.raise_for_status()
        return response.json().get("data", [])
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any] | AsyncGenerator[Dict[str, Any], None]:
        """Chat completion con supporto streaming e tools"""
        
        payload = {
            "model": model or self.config.model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
            "stream": stream,
        }
        
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        
        if stream:
            return self._stream_chat(payload)
        
        response = await self.client.post("/v1/chat/completions", json=payload)
        response.raise_for_status()
        return response.json()
    
    async def _stream_chat(self, payload: Dict) -> AsyncGenerator[Dict[str, Any], None]:
        """Streaming chat completion - yields chunk per token"""
        async with self.client.stream("POST", "/v1/chat/completions", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("data: "):
ReAct Agent per RaidbrowsAI
Cycle agente-tool-observation con supporto tool calling
"""
import json
import asyncio
from typing import AsyncGenerator, Optional, List, Dict, Any
from dataclasses import dataclass


@dataclass
class Tool:
    """Definizione tool per l'agente"""
    name: str
    description: str
    parameters: Dict[str, Any]
    
    async def execute(self, **kwargs) -> Any:
        """Esegui il tool con i parametri forniti"""
        raise NotImplementedError


@dataclass 
class ToolResult:
    """Risultato esecuzione tool"""
    success: bool
    data: Any
    error: Optional[str] = None


class ReActAgent:
    """
    ReAct (Reasoning and Acting) Agent cycle per RaidbrowsAI
    Supporta tool calling, memory e iterazioni controllate
    """
    
    def __init__(
        self, 
        provider,
        tools: Optional[List[Tool]] = None,
        max_iterations: int = 15,
        system_prompt: Optional[str] = None
    ):
        self.provider = provider
        self.tools = {t.name: t for t in (tools or [])}
        self.max_iterations = max_iterations
        self.system_prompt = system_prompt or "Sei un assistente IA per browser con accesso a tools."
        self.iteration = 0
        self.intermediate_steps = []  # [(action, observation)]
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
    
    async def run(
        self, 
        user_input: str, 
        context: Optional[Dict] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Esegui il ciclo ReAct:
        Thought -> Action -> Observation -> ... -> Final Answer
        Yields streaming chunks
        """
        self.iteration = 0
        self.intermediate_steps = []
        
        # Prepara il messaggio di sistema
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": user_input})
        
        # Primo turno
        chunk = await self.provider.chat_completion(
            messages=messages,
            stream=False
        )
        
        if chunk.get("choices")[0].get("finish_reason") == "stop":
            yield {"role": "assistant", "content": chunk["choices"][0]["message"]["content"]}
            return
        
        # Ciclo ReAct
        while self.iteration < self.max_iterations:
            self.iteration += 1
            
            # Estrai thought e action dal messaggio
            message = chunk["choices"][0]["message"]
            content = message.get("content", "")
            
            # Parsing semplificato: cerca pattern Thought/Action/Action Input
            thought, action, action_input = self._parse_react_message(content)
            
            if action is None:
                # Nessun tool, risposta finale
                yield {"role": "assistant", "content": content}
                return
            
            # Eseguzione thought
            yield {"role": "thought", "content": thought or "Thinking..."}
            
            # Esecuzione action
            if action in self.tools:
                tool = self.tools[action]
                try:
                    result = await tool.execute(**action_input)
                    observation = ToolResult(success=True, data=result).model_dump()
                except Exception as e:
                    observation = ToolResult(success=False, data=None, error=str(e)).model_dump()
            else:
                observation = {"error": f"Tool '{action}' non trovato"}
            
            # Aggiungi observation al contesto e chiedi prossimo passo
            messages.append({
                "role": "assistant", 
                "content": content,
                "tool_calls": [{"name": action, "arguments": action_input}]
            })
            messages.append({
                "role": "user", 
                "content": f"Osservazione: {json.dumps(observation)}"
            })
            
            # Richiesta prossimo passo
            chunk = await self.provider.chat_completion(
                messages=messages,
                stream=False
            )
            
            # Verifica se è una risposta finale
            if chunk["choices"][0].get("finish_reason") == "stop":
                final_msg = chunk["choices"][0]["message"]["content"]
                yield {"role": "assistant", "content": final_msg}
                return
        
        # Max iterations raggiunto
        yield {"role": "assistant", "content": "Massimo numero di iterazioni raggiunto."}
    
    def _parse_react_message(self, content: str) -> tuple:
        """Parsa un messaggio ReAct estraendo Thought, Action, Action Input"""
        thought = None
        action = None
        action_input = {}
        
        # Pattern semplici
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if line.lower().startswith('thought:'):
                thought = line[len('Thought:'):].strip()
            elif line.lower().startswith('action:'):
                action = line[len('Action:'):].strip().split('(')[0].strip()
                # Estrai arguments
                if '(' in line:
                    args_str = line[line.index('(')+1:line.rindex(')')]
                    try:
                        action_input = json.loads(args_str)
                    except:
                        action_input = {"input": args_str}
            elif line.lower().startswith('action input:'):
                try:
                    action_input = json.loads(line[len('Action Input:'):].strip())
                except:
                    pass
        
        # Se non abbiamo thought, prendi il primo pensiero
        if thought is None and content:
            thought = "Analisi in corso..."
        
        # Se non abbiamo action, cerca qualsiasi riferimento a tool
        if action is None:
            # Cerca pattern tool_name(params)
            import re
            matches = re.findall(r'(\w+)\s*\((.+?)\)', content)
            if matches:
                action = matches[0][0]
                try:
                    action_input = json.loads('{' + matches[0][1] + '}')
                except:
                    action_input = {}
        
        return thought, action, action_input


# Tool examples per browser operations
class BrowserNavigateTool(Tool):
Vector Memory per RaidbrowsAI usando ChromaDB
Memoria vettoriale per storage contesto e retrieved memories
"""
import json
import asyncio
from typing import AsyncGenerator, Optional, List, Dict, Any
from dataclasses import dataclass, field
import chromadb
from chromadb.config import Settings as ChromaSettings


@dataclass
class MemoryEntry:
    """Voce di memoria con embedding"""
    id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None


class VectorMemory:
    """
    Memoria vettoriale basata su ChromaDB per RaidbrowsAI
    Supporta add/search/delete operations con persistence
    """
    
    def __init__(
        self, 
        collection_name: str = "raidbrowsai",
        persist_path: str = "./chroma_db"
    ):
        self.client = chromadb.Client(
            ChromaSettings(
                persist_path=persist_path,
                anonymized_telemetry=False
            )
        )
        self.collection = self.client.get_or_create_collection(
N8N Client per RaidbrowsAI
Cliente per eseguire/triggerare workflow n8n via API
"""
import json
import asyncio
from typing import AsyncGenerator, Optional, List, Dict, Any
import aiohttp


class N8NClient:
    """
    Client per l'integrazione con n8n self-hosted
    Supporta execute workflow, trigger webhook, list workflows
    """
    
    def __init__(
        self, 
        base_url: str = "http://localhost:5678",
        api_key: Optional[str] = None,
        timeout: int = 30
    ):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.timeout = timeout
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        headers = {}
        if self.api_key:
            headers["X-N8N-API-KEY"] = self.api_key
        self.session = aiohttp.ClientSession(
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def list_workflows(self) -> List[Dict[str, Any]]:
        """Elenca tutti i workflow n8n"""
        if not self.session:
            raise RuntimeError("Client not initialized")
        
        async with self.session.get(
            f"{self.base_url}/rest/workflows"
        ) as response:
            response.raise_for_status()
            data = await response.json()
            return data.get("data", [])
    
    async def execute_workflow(
        self, 
        workflow_name: str,
        trigger_data: Dict[str, Any]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Esegui un workflow n8n e restituisci lo streaming dei risultati"""
        if not self.session:
            raise RuntimeError("Client not initialized")
        
        # First, find the workflow ID
        workflows = await self.list_workflows()
        workflow = next(
            (w for w in workflows if w.get("name") == workflow_name), 
            None
        )
        
        if not workflow:
            raise ValueError(f"Workflow '{workflow_name}' not found")
        
        workflow_id = workflow["id"]
        
        # Execute the workflow
        payload = {
            "workflowId": workflow_id,
            "data": trigger_data
        }
        
        async with self.session.post(
            f"{self.base_url}/rest/workflows/{workflow_id}/execute",
            json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.content:
                if line:
                    yield json.loads(line.decode())
    
    async def trigger_webhook(
        self, 
        webhook_id: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Triggera un webhook n8n"""
        if not self.session:
            raise RuntimeError("Client not initialized")
        
        payload = {"event": data}
        
        async with self.session.post(
            f"{self.base_url}/webhook/{webhook_id}",
            json=payload
        ) as response:
            response.raise_for_status()
            return await response.json()


# Factory function
def create_n8n_client(
    base_url: str = "http://localhost:5678",
    api_key: Optional[str] = None
) -> N8NClient:
    """Crea istanza di N8NClient"""
    return N8NClient(base_url, api_key)
