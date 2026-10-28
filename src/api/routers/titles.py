"""POST /titles/generate, POST /titles/score."""
from __future__ import annotations

import re
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.api.limiter import Tier, limiter
from src.auth.dependencies import get_current_user
from src.database.models import User

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["titles"])


class TitleGenerateRequest(BaseModel):
    topic: str
    niche: str
    style: Optional[str] = None
    count: int = 5


class TitleSuggestion(BaseModel):
    title: str
    score: float
    reason: str


class TitleScoreFeatures(BaseModel):
    """Per-feature breakdown surfaced alongside the headline score so
    the agent (or human) can see *why* the title scored where it did
    without needing a second round-trip."""

    length: int = Field(..., ge=0, description="Character length of the title")
    word_count: int = Field(..., ge=0)
    has_number: bool = Field(..., description="True if the title contains at least one digit")
    has_question: bool = Field(..., description="True if the title is phrased as a question")
    emotional_score: float = Field(
        ..., ge=0.0, le=1.0, description="0-1 score for emotional charge"
    )
    trending_score: float = Field(
        ..., ge=0.0, le=1.0, description="0-1 score for currently-trending keyword overlap"
    )


class TitleScoreResponse(BaseModel):
    """CTR-focused title score with per-feature breakdown."""

    title: str
    score: int = Field(..., ge=0, le=100, description="Headline CTR score (0-100)")
    features: TitleScoreFeatures
    recommendations: list[str] = Field(
        ...,
        description="Top 3 actionable rewrites (e.g. 'Shorten to 50-60 characters for mobile')",
    )


# Per-niche prompt guidance. Keyed by the frontend's niche slugs (with aliases).
# Each entry tells the model what the content actually is, which CTR levers work
# best for that audience, and example title *shapes* (not fill-in templates) so it
# stays specific instead of falling back to generic "documentary" phrasing.
_NICHE_GUIDANCE: dict[str, str] = {
    "tech_reviews": (
        "CONTENT TYPE: Tech reviews, comparisons, and buying advice.\n"
        "AUDIENCE WANTS: a verdict, real specs/prices, and whether it's worth their money.\n"
        "BEST LEVERS: value verdict tease, head-to-head comparison (vs the obvious rival), a "
        "surprising flaw or strength, the price, the year, and the exact product/model name.\n"
        "EXAMPLE SHAPES: 'I Used the <Product> for 30 Days — Here's the Truth', "
        "'<Product A> vs <Product B>: Don't Waste Your Money', '<Product> Is Not What They Told You'.\n"
        "AVOID: overhyping; keep the verdict honest and the product name exact."
    ),
    "gaming": (
        "CONTENT TYPE: Gaming — gameplay, challenges, rankings, clutch moments, drama.\n"
        "AUDIENCE WANTS: high energy, insane moments, stakes, and rankings.\n"
        "BEST LEVERS: a clutch/insane outcome tease, self-imposed challenge ('I did X'), "
        "rankings (best/worst), what's at stake, and the exact game/mode/character names. "
        "Strategic CAPS for energy are normal here.\n"
        "EXAMPLE SHAPES: 'This <Game> Clutch Should Be ILLEGAL', "
        "'I Beat <Game> Without <Constraint>', 'Ranking Every <Thing> in <Game>'.\n"
        "AVOID: vague hype with no specific game detail."
    ),
    "education_howto": (
        "CONTENT TYPE: Tutorials, how-tos, and explainers.\n"
        "AUDIENCE WANTS: a clear outcome/skill and trust that it'll actually work.\n"
        "BEST LEVERS: the concrete result/benefit, a timeframe ('in 10 minutes'), a number of "
        "steps/mistakes, a common mistake to avoid, and a genuine curiosity gap about a concept.\n"
        "EXAMPLE SHAPES: 'How to <Result> (Even If <Obstacle>)', "
        "'<N> <Topic> Mistakes That Are Costing You', 'The Fastest Way to <Result>'.\n"
        "AVOID: clickbait that over-promises; clarity beats hype here."
    ),
    "entertainment_vlogs": (
        "CONTENT TYPE: Vlogs, challenges, and personality-driven entertainment.\n"
        "AUDIENCE WANTS: a story, emotion, and a reason to care about the creator's day.\n"
        "BEST LEVERS: an emotional or dramatic hook, a story tease ('the day everything changed'), "
        "relatable stakes, a surprising turn, and real names/places involved.\n"
        "EXAMPLE SHAPES: 'I Did Not Expect This to Happen...', "
        "'<Event> Went Completely Wrong', 'We Tried <Thing> and It Got Real'.\n"
        "AVOID: generic 'a day in my life' phrasing with no hook."
    ),
    "lifestyle": (
        "CONTENT TYPE: Lifestyle — routines, transformations, habits, advice.\n"
        "AUDIENCE WANTS: relatable problems, aspirational results, and a clear payoff.\n"
        "BEST LEVERS: a transformation/result, before-and-after, a relatable struggle, a specific "
        "habit or timeframe, and an honest personal angle.\n"
        "EXAMPLE SHAPES: 'I Tried <Habit> for 30 Days — Here's What Changed', "
        "'The <Routine> That Actually Fixed My <Problem>', 'Why I Quit <Thing>'.\n"
        "AVOID: vague self-help phrasing with no concrete result."
    ),
    "music_creative": (
        "CONTENT TYPE: Music & creative — tracks, covers, production, reactions, making-of.\n"
        "AUDIENCE WANTS: the artist/song, the craft, and authenticity.\n"
        "BEST LEVERS: the exact artist/track/genre names, a 'making of' or behind-the-scenes angle, "
        "a reaction/first-listen hook, and collabs.\n"
        "EXAMPLE SHAPES: 'Making <Track> From Scratch', "
        "'First Time Hearing <Artist> — <Song>', 'How <Artist> Built <Song>'.\n"
        "AVOID: dropping the specific artist/track name in favor of vague phrasing."
    ),
    "news_politics": (
        "CONTENT TYPE: News, current events, and political analysis.\n"
        "AUDIENCE WANTS: what happened, who's involved, and why it matters now.\n"
        "BEST LEVERS: the key figure/event/place, the stakes and consequences, timeliness, and a "
        "'what this really means' analysis angle. Stay factual.\n"
        "EXAMPLE SHAPES: 'What <Event> Actually Means for <Group>', "
        "'<Figure> Just Changed <Thing> — Here's Why', 'The Real Story Behind <Event>'.\n"
        "AVOID: false sensationalism or claims the description doesn't support; credibility matters most."
    ),
    "commentary_essay": (
        "CONTENT TYPE: Video essays, commentary, and deep-dive takes.\n"
        "AUDIENCE WANTS: a sharp thesis, a fresh or contrarian angle, and intrigue about the subject.\n"
        "BEST LEVERS: a bold/contrarian claim, a pointed question, the subject's exact name, and a "
        "curiosity gap that promises a payoff.\n"
        "EXAMPLE SHAPES: 'The Problem With <Subject>', 'Why <Subject> Fell Off', "
        "'<Subject> Was Never What You Thought'.\n"
        "AVOID: the overused 'Untold Story / Hidden Truth' framing; make the take specific."
    ),
    "sports": (
        "CONTENT TYPE: Sports & competition — games, matchups, highlights, rivalries, drama.\n"
        "AUDIENCE WANTS: the matchup, the stakes, and the dramatic/emotional moment.\n"
        "BEST LEVERS: 'X vs Y' matchups, what's on the line (title, seed, record, bid), a heated or "
        "disrespectful moment, a clutch/upset outcome tease, and the exact team/player names. "
        "Strategic CAPS for big moments are normal here.\n"
        "EXAMPLE SHAPES: '<Team A> vs <Team B>: EVERYTHING on the Line', "
        "'<Player> Got DISRESPECTFUL After This...', '<Team> Did the IMPOSSIBLE in the Finals'.\n"
        "AVOID: dropping the team/player names in favor of vague phrasing."
    ),
}

# Map alternate / human-readable niche values to the canonical guidance keys.
_NICHE_ALIASES: dict[str, str] = {
    "tech": "tech_reviews",
    "technology": "tech_reviews",
    "education": "education_howto",
    "howto": "education_howto",
    "how-to": "education_howto",
    "entertainment": "entertainment_vlogs",
    "vlogs": "entertainment_vlogs",
    "vlog": "entertainment_vlogs",
    "music": "music_creative",
    "creative": "music_creative",
    "news": "news_politics",
    "politics": "news_politics",
    "commentary": "commentary_essay",
    "essay": "commentary_essay",
    "sport": "sports",
    "athletics": "sports",
}


def _build_title_prompt(topic: str, niche: str, style: Optional[str], count: int) -> str:
    """Assemble the title-generation prompt with niche-specific guidance."""
    key = (niche or "").strip().lower().replace(" ", "_").replace("&", "and")
    key = key.replace("_and_", "_")
    guidance = _NICHE_GUIDANCE.get(key) or _NICHE_GUIDANCE.get(_NICHE_ALIASES.get(key, ""))
    if not guidance:
        guidance = (
            "CONTENT TYPE: Infer it from the description.\n"
            "BEST LEVERS: curiosity gap, real stakes/consequences, conflict or matchup, "
            "emotional hook, a surprising result, and the exact names/places involved.\n"
            "AVOID: generic phrasing that could describe any video."
        )
    style_line = f"Creator's style preference: {style}\n" if style else ""
    return f"""You are a world-class YouTube title strategist. Write {count} titles that maximize click-through rate for the SPECIFIC video described below.

Video description: {topic}
Niche/Category: {niche}
{style_line}
THIS NICHE'S PLAYBOOK:
{guidance}

STEP 1 — Read the description and confirm what the video actually is. Match the energy of the niche playbook above; do NOT default to a documentary/educational tone unless the niche is Education.

STEP 2 — KEEP THE SPECIFICS. Pull the concrete, audience-relevant details straight from the description and put them in the titles: real names, team/player/product names, event names, scores, seasons, prices, stakes, and matchups. Specific proper nouns are what this channel's audience recognizes and clicks. Never replace a real name with a vague phrase.

STEP 3 — Use the niche's best levers above, mixing a DIFFERENT angle into each title so the {count} options don't feel repetitive.

RULES:
- Front-load the hook; keep it UNDER 50 characters (past 50 it truncates with "..." on mobile).
- Sound like a real top creator in this niche, not an AI.
- Use the EXAMPLE SHAPES as inspiration for structure only — fill them with the real details from THIS description, never leave a placeholder.
- BANNED generic openers (do not use): "The Untold Story of", "What They Don't Tell You", "The Hidden Truth Behind", "The Dark Side of", "The Dark History of", "Exposed", "Revealed", "Shocking Truth". They read as AI filler.
- Don't promise anything the description doesn't support.

Output ONLY a numbered list, one per line, exactly:
1. [Title] | Score: [0-100] | Reason: [one concrete sentence on why it earns the click]
"""


def _get_title_recommendations(features) -> list[str]:
    """Generate title improvement recommendations."""
    recs: list[str] = []
    if features.char_length > 50:
        recs.append("Shorten to under 50 characters — past 50 it truncates with '...' on mobile")
    elif features.char_length < 20:
        recs.append("Add a bit more context (aim for ~30-50 characters)")
    if not features.has_number:
        recs.append("Add a specific number for higher CTR")
    if features.emotional_score < 0.3:
        recs.append("Use more emotional language")
    return recs[:3]


@router.post("/titles/generate", response_model=list[TitleSuggestion])
@limiter.limit(Tier.LLM_HEAVY)
async def generate_titles(
    request: Request,
    body: TitleGenerateRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate optimized title suggestions for a topic (auth required)."""
    request.state.current_user = current_user
    try:
        from src.features.ai_writer import AIWriter

        writer = AIWriter()
        writer.set_budget_context(current_user.id, current_user.plan or "free")

        prompt = _build_title_prompt(body.topic, body.niche, body.style, body.count)

        response = writer._call_claude(prompt, max_tokens=800, feature="titles.generate")

        def _clean_title(raw: str) -> str:
            """Strip markdown bold/italic and surrounding quotes the LLM adds."""
            cleaned = raw.strip()
            cleaned = re.sub(r"^[*_\s\"']+|[*_\s\"']+$", "", cleaned)
            return cleaned.strip()

        suggestions: list[TitleSuggestion] = []
        if response:
            for line in response.strip().split("\n"):
                line = line.strip()
                if not line or not any(c.isdigit() for c in line[:3]):
                    continue

                title_match = re.match(
                    r"^\d+\.\s*(.+?)\s*\|\s*Score:\s*(\d+)\s*\|\s*Reason:\s*(.+)$",
                    line,
                )
                if title_match:
                    suggestions.append(
                        TitleSuggestion(
                            title=_clean_title(title_match.group(1)),
                            score=float(title_match.group(2)),
                            reason=title_match.group(3).strip(),
                        )
                    )
                else:
                    parts = line.split("|")
                    if parts:
                        title = _clean_title(re.sub(r"^\d+\.\s*", "", parts[0]))
                        if title and len(title) > 5:
                            suggestions.append(
                                TitleSuggestion(
                                    title=title,
                                    score=75.0,
                                    reason="AI-generated title for your topic",
                                )
                            )

        # Fallback when the LLM didn't produce parseable output.
        if not suggestions:
            def extract_topic(text: str) -> str:
                """Extract a usable topic (3-6 words) that preserves key context."""
                location_pattern = (
                    r"\b(france|french|germany|german|england|english|america|american|"
                    r"rome|roman|china|chinese|japan|japanese|russia|russian|spain|"
                    r"spanish|italy|italian|britain|british)\b"
                )
                location_match = re.search(location_pattern, text.lower())
                location = location_match.group(1).title() if location_match else None

                time_pattern = r"\b(\d{4}s?|\d{2}th century|ancient|medieval|modern|victorian)\b"
                time_match = re.search(time_pattern, text.lower())
                time_period = time_match.group(1) if time_match else None

                stop_words = {
                    "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
                    "but", "is", "are", "was", "were", "be", "been", "being", "have",
                    "has", "had", "about", "not", "commonly", "known", "first", "episode",
                    "that", "this", "with", "from", "by", "as", "it", "its", "they",
                    "them", "their", "secrets",
                }

                words = text.lower().replace(",", " ").replace(".", " ").split()
                key_words = [w.strip() for w in words if len(w) > 3 and w not in stop_words]

                topic_parts: list[str] = []
                descriptive = [
                    w for w in key_words
                    if w not in (location.lower() if location else "", time_period or "")
                ][:3]
                if descriptive:
                    topic_parts.extend(descriptive)

                if location and location.lower() not in " ".join(topic_parts):
                    topic_parts.append(location)

                if time_period and len(" ".join(topic_parts)) < 25:
                    topic_parts.append(time_period)

                if topic_parts:
                    topic = " ".join(topic_parts).title()
                    topic = "".join(c for c in topic if c.isalnum() or c == " ").strip()
                    return topic if len(topic) <= 40 else topic[:40].rsplit(" ", 1)[0]

                return " ".join(words[:5]).title()[:35]

            short_topic = extract_topic(body.topic)
            niche_patterns = {
                "gaming": [
                    "I Tried {} for 24 Hours",
                    "The {} Challenge Gone Wrong",
                    "{} Tips That ACTUALLY Work",
                    "Why {} is BROKEN",
                    "Ranking Every {}",
                ],
                "tech_reviews": [
                    "Is {} Worth It in 2026?",
                    "{} - Honest Review",
                    "{} vs The Competition",
                    "Why {} Changes Everything",
                    "Don't Buy {} Until You Watch This",
                ],
                "education_howto": [
                    "How to {} (Step by Step)",
                    "{} Mistakes You're Probably Making",
                    "The Fastest Way to {}",
                    "{} Explained Simply",
                    "{} - What Actually Works",
                ],
                "entertainment_vlogs": [
                    "{} Did Not Go as Planned",
                    "{} Went Completely Wrong",
                    "The Day {} Changed Everything",
                    "We Tried {} and It Got Real",
                    "I Can't Believe {} Happened",
                ],
                "lifestyle": [
                    "I Tried {} for 30 Days",
                    "{} Changed Everything",
                    "The {} That Actually Worked",
                    "Why I Quit {}",
                    "My Honest {} Results",
                ],
                "music_creative": [
                    "Making {} From Scratch",
                    "First Time Hearing {}",
                    "How {} Was Made",
                    "{} - Behind the Scenes",
                    "Reacting to {}",
                ],
                "news_politics": [
                    "What {} Actually Means",
                    "The Real Story Behind {}",
                    "{} - Here's Why It Matters",
                    "{} Just Changed Everything",
                    "Breaking Down {}",
                ],
                "commentary_essay": [
                    "The Problem With {}",
                    "Why {} Fell Off",
                    "{} Was Never What You Thought",
                    "Let's Talk About {}",
                    "The Truth About {}",
                ],
                "sports": [
                    "{} Came Down to THIS",
                    "Everything Was on the Line: {}",
                    "{} Got HEATED",
                    "The {} Nobody Saw Coming",
                    "{} - Championship on the Line",
                ],
            }
            # Neutral high-CTR default (curiosity + stakes), NOT documentary-style,
            # so non-educational topics don't get forced into "Dark History of..."
            default_patterns = [
                "{} Got Out of Hand",
                "Everything Was on the Line: {}",
                "Nobody Expected This in {}",
                "{} - How It Really Went Down",
                "This Changed {} Forever",
            ]
            fb_key = (body.niche or "").strip().lower().replace(" ", "_").replace("&", "and")
            fb_key = fb_key.replace("_and_", "_")
            fb_key = _NICHE_ALIASES.get(fb_key, fb_key)
            patterns = niche_patterns.get(fb_key, default_patterns)

            for i, pattern in enumerate(patterns[:body.count]):
                suggestions.append(
                    TitleSuggestion(
                        title=pattern.format(short_topic),
                        score=70.0 + i * 2,
                        reason=f"Proven title pattern for {body.niche} content",
                    )
                )

        return suggestions[: body.count]

    except Exception as e:
        logger.error(f"Title generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/titles/score", response_model=TitleScoreResponse)
@limiter.limit(Tier.READ)
async def score_title(
    request: Request,
    title: str = Query(..., max_length=300),
    niche: str = Query(default="general", max_length=50),
    current_user: User = Depends(get_current_user),
) -> TitleScoreResponse:
    """Score an existing title (auth required)."""
    request.state.current_user = current_user
    try:
        from src.features.title_analyzer import TitleAnalyzer

        analyzer = TitleAnalyzer()
        features = analyzer.analyze(title)

        score = 50
        # Keep titles < 50 chars — above that they truncate to "..." on mobile.
        if features.char_length <= 50:
            score += 10
        else:
            score -= 8
        if features.has_number:
            score += 8
        if features.emotional_score > 0.5:
            score += 10
        if features.has_question or features.has_exclamation:
            score += 5
        if features.trending_score > 0.3:
            score += 8

        return TitleScoreResponse(
            title=title,
            score=min(100, max(0, score)),
            features=TitleScoreFeatures(
                length=features.char_length,
                word_count=features.word_count,
                has_number=features.has_number,
                has_question=features.has_question,
                emotional_score=features.emotional_score,
                trending_score=features.trending_score,
            ),
            recommendations=_get_title_recommendations(features),
        )
    except Exception as e:
        logger.error(f"Title scoring failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/titles/packaging-score")
@limiter.limit(Tier.LLM_HEAVY)
async def packaging_score(
    request: Request,
    title: str = Query(..., max_length=300),
    idea: Optional[str] = Query(default=None, max_length=500),
    current_user: User = Depends(get_current_user),
):
    """MrBeast-style packaging rubric for a title: per-principle scores
    (curiosity gap, extremity, clarity, specificity), the hard <50-char mobile
    rule, the biggest weakness, and stronger sub-50-char rewrites. The
    explainable companion to the ML reach predictor."""
    from src.features.packaging_rubric import score_title

    result = score_title(
        title, idea=idea, user_id=current_user.id,
        plan=getattr(current_user, "plan", "free"),
    )
    if result.get("error") == "empty_title":
        raise HTTPException(status_code=422, detail="Title is empty.")
    return result
