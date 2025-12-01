# 🎭 Improv Battle Voice Agent  
### Day 10 — Murf AI Voice Agents Challenge

This project is a **voice-first improv game show agent** built using  
**LiveKit Agents + Murf Falcon TTS + Gemini + Deepgram**.

The AI acts as a high-energy, charismatic host who:
- Greets the player  
- Asks their name  
- Explains the rules  
- Delivers improv scenarios  
- Waits for your "performance"  
- Reacts with witty, playful, and realistic feedback  
- Tracks rounds and ends with a personalized summary  

This is one of the most entertaining agents in the entire 10-day challenge.

---

## 🚀 Features

### 🎙️ AI Improv Host Persona
- High-energy, witty, TV-game-show-style host  
- Natural reactions (supportive → teasing → surprised → neutral)  
- Varies tone while staying respectful and fun  

### 🎭 Structured 3-Round Improv Game
- Host asks for your name  
- Gives 3 improv scenarios (randomized)  
- You act out the scene  
- Say **“End Scene”** to finish a round  
- Host reacts and stores feedback  

### 🧠 Game State Tracking
```python
improv_state = {
    "player_name": str,
    "current_round": int,
    "max_rounds": 3,
    "rounds": [
        {"scenario": "...", "reaction": "..."}
    ],
    "phase": "intro" | "playing" | "done"
}
