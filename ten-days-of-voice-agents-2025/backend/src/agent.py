import logging
import json
import random
import asyncio
from typing import List, Dict, Any, Annotated, Optional
from pathlib import Path

from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RoomInputOptions,
    WorkerOptions,
    cli,
    metrics,
    tokenize,
    function_tool,
)
from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("improv-agent")

# Load environment
load_dotenv(".env.local")

# ============================================================
# GAME STATE & LOGIC
# ============================================================

SCENARIOS = [
    "You are a time-travelling tour guide explaining modern smartphones to someone from the 1800s.",
    "You are a restaurant waiter who must calmly tell a customer that their order has escaped the kitchen.",
    "You are a customer trying to return an obviously cursed object to a very skeptical shop owner.",
    "You are a cat trying to convince a dog to let you share the bed.",
    "You are a superhero whose only power is making toast slightly faster, interviewing for the Avengers.",
    "You are a alien trying to explain to your leader why you failed to conquer Earth (it was the pizza).",
]

class ImprovGame:
    def __init__(self):
        self.player_name: Optional[str] = None
        self.current_round: int = 0
        self.max_rounds: int = 3
        self.rounds: List[Dict[str, str]] = [] # [{"scenario": ..., "reaction": ...}]
        self.phase: str = "intro" # intro, playing, done
        self.current_scenario: Optional[str] = None

    def start_game(self, name: str):
        self.player_name = name
        self.phase = "playing"
        self.current_round = 0
        logger.info(f"Game started for {name}")

    def get_next_scenario(self) -> Optional[str]:
        if self.current_round >= self.max_rounds:
            self.phase = "done"
            return None
        
        # Pick a random scenario that hasn't been used (if possible)
        scenario = random.choice(SCENARIOS)
        self.current_scenario = scenario
        self.current_round += 1
        return scenario

    def record_round(self, reaction: str):
        if self.current_scenario:
            self.rounds.append({
                "scenario": self.current_scenario,
                "reaction": reaction
            })
            logger.info(f"Round {self.current_round} recorded. Reaction: {reaction}")

# ============================================================
# AGENT IMPLEMENTATION
# ============================================================

class ImprovHost(Agent):
    def __init__(self, game: ImprovGame) -> None:
        self.game = game
        super().__init__(
            instructions=self._prompt()
        )

    def _prompt(self):
        return """
You are the charismatic, high-energy, and witty host of "Improv Battle", a voice-first improv game show.

**Your Goal:**
Guide the player through 3 rounds of short-form improv. You set the scene, they act, and you react.

**Current State:**
- Player Name: {player_name}
- Round: {current_round}/{max_rounds}

**Persona:**
- **Tone:** Energetic, sharp, slightly theatrical (think game show host).
- **Style:** You are supportive but honest. If a joke falls flat, you can tease them playfully. If they are great, praise them enthusiastically.
- **Reactions:** Varied! Don't always be nice. Be realistic. Use humor.

**Game Flow:**
1. **Intro:** 
   - If you know the player's name, welcome them by name and explain the rules.
   - If you DON'T know the name, ask for it. When they tell you, call `set_player_name`.
   - Rules: "I'll give you a scenario, you act it out. When you're done, say 'End Scene' or just stop talking, and I'll judge you."
2. **The Rounds:**
   - Use the `get_scenario` tool to get a new scenario.
   - Announce the scenario clearly. "Your scenario is..."
   - Tell them to "Action!" or "Go!".
   - **Listen** to their performance.
   - **React**: Once they finish (or if they struggle), give your feedback. Be specific about what they said.
   - Call `record_round_reaction` to save your feedback.
   - Move to the next round immediately.
3. **The End:**
   - When `get_scenario` returns nothing (or indicates end), wrap up.
   - Give a final summary of their performance based on the rounds.
   - Thank them and say goodbye.

**Important:**
- **ALWAYS** use the `get_scenario` tool to get the scenario text. Do not invent your own scenarios unless the tool fails.
- **ALWAYS** use `record_round_reaction` after you deliver your feedback for a round.
- If the user says "stop game" or "quit", politely end the show.
""".format(
    player_name=self.game.player_name or "Unknown",
    current_round=self.game.current_round,
    max_rounds=self.game.max_rounds
)

    @function_tool
    async def set_player_name(self, name: Annotated[str, "The name of the player"]):
        """Call this when the player tells you their name."""
        logger.info(f"Setting player name to {name}")
        self.game.start_game(name)
        return f"Player name set to {name}. Game started! Now explain the rules and start Round 1."

    @function_tool
    async def get_scenario(self):
        """Get the next improv scenario. Returns None if game is over."""
        try:
            scenario = self.game.get_next_scenario()
            if scenario:
                return f"Scenario for Round {self.game.current_round}: {scenario}"
            else:
                return "GAME_OVER"
        except Exception as e:
            logger.error(f"Error getting scenario: {e}", exc_info=True)
            return "Error: Could not generate scenario. Please try again."

    @function_tool
    async def record_round_reaction(self, reaction: Annotated[str, "Your feedback/reaction to the player's performance"]):
        """Call this AFTER you have spoken your reaction to the player."""
        self.game.record_round(reaction)
        return "Reaction recorded. Now move to the next round."

# ============================================================
# PREWARM
# ============================================================

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

# ============================================================
# ENTRYPOINT
# ============================================================

async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}
    
    game = ImprovGame()

    # Try to get player name from metadata
    initial_greeting = "Welcome to Improv Battle! I'm your host. What's your name, contestant?"
    
    # Wait a bit for participants to be populated if needed, though usually they are there on connect
    # But let's check existing participants
    for p in ctx.room.remote_participants.values():
        if p.metadata:
            try:
                md = json.loads(p.metadata)
                if "player_name" in md and md["player_name"]:
                    game.start_game(md["player_name"])
                    initial_greeting = f"Welcome to Improv Battle, {game.player_name}! I'm your host. Are you ready to improvise?"
                    break
            except Exception as e:
                logger.warning(f"Failed to parse metadata: {e}")

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(
            voice="en-US-matthew", 
            style="Promo", 
            tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
            text_pacing=True,
        ),
        vad=ctx.proc.userdata["vad"],
        turn_detection=MultilingualModel(),
        preemptive_generation=True,
    )

    # Track usage
    usage = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on(event: MetricsCollectedEvent):
        metrics.log_metrics(event.metrics)
        usage.collect(event.metrics)

    async def finish():
        logger.info(usage.get_summary())

    ctx.add_shutdown_callback(finish)

    await session.start(
        agent=ImprovHost(game),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        ),
    )

    await ctx.connect()

    await session.say(
        initial_greeting,
        add_to_chat_ctx=True
    )

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm
        )
    )
