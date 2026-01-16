#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Usage Tracker - Centralized logging for all AI model usage
Tracks tokens, costs, and performance metrics for Anthropic and OpenAI models.
"""

import json
import time
from typing import Dict, Any, Optional
from src.db.database import DatabaseManager


# Pricing configuration (USD per million tokens)
PRICING = {
    'anthropic': {
        'claude-3-5-sonnet-20241022': {'input': 3.00, 'output': 15.00},
        'claude-sonnet-4-20250514': {'input': 3.00, 'output': 15.00},
        'claude-3-5-haiku-20241022': {'input': 0.25, 'output': 1.25},
        'claude-3-opus-20240229': {'input': 15.00, 'output': 75.00},
        'claude-3-sonnet-20240229': {'input': 3.00, 'output': 15.00},
        'claude-3-haiku-20240307': {'input': 0.25, 'output': 1.25},
    },
    'openai': {
        'text-embedding-3-small': {'input': 0.02, 'output': 0.0},
        'gpt-4o-mini-transcribe': {'per_minute': 0.006},
    }
}


class AIUsageTracker:
    """Tracks and logs AI model usage to the database."""

    def __init__(self, application: str = 'cupido_backend'):
        self.application = application

    def calculate_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        audio_duration_seconds: float = 0
    ) -> float:
        """Calculate estimated cost in USD."""
        if provider not in PRICING or model not in PRICING[provider]:
            return 0.0

        pricing = PRICING[provider][model]

        # For audio transcription (charges by duration)
        if 'per_minute' in pricing:
            return (audio_duration_seconds / 60) * pricing['per_minute']

        # For text models (charges by tokens)
        input_cost = (input_tokens / 1_000_000) * pricing.get('input', 0)
        output_cost = (output_tokens / 1_000_000) * pricing.get('output', 0)

        return input_cost + output_cost

    def log_usage(
        self,
        provider: str,
        model: str,
        usage_type: str,
        function_name: str,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        audio_duration_seconds: Optional[float] = None,
        response_time_ms: Optional[int] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[int]:
        """
        Log AI usage to the database.

        Args:
            provider: 'anthropic' or 'openai'
            model: Model identifier (e.g., 'claude-3-5-sonnet-20241022')
            usage_type: Type of usage (e.g., 'search_extraction', 'transcription')
            function_name: Source function/method name
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            audio_duration_seconds: Duration for audio transcription
            response_time_ms: Response time in milliseconds
            success: Whether the call succeeded
            error_message: Error message if failed
            context: Additional context (user_id, property_id, etc.)

        Returns:
            ID of the inserted log record, or None on failure
        """
        try:
            # Calculate total tokens
            total_tokens = None
            if input_tokens is not None or output_tokens is not None:
                total_tokens = (input_tokens or 0) + (output_tokens or 0)

            # Calculate estimated cost
            estimated_cost = self.calculate_cost(
                provider=provider,
                model=model,
                input_tokens=input_tokens or 0,
                output_tokens=output_tokens or 0,
                audio_duration_seconds=audio_duration_seconds or 0
            )

            # Prepare context JSON
            context_json = json.dumps(context or {}, ensure_ascii=False)

            with DatabaseManager() as db:
                query = """
                    INSERT INTO ai_usage_log (
                        provider, model, usage_type, application, function_name,
                        input_tokens, output_tokens, total_tokens,
                        audio_duration_seconds, estimated_cost_usd,
                        response_time_ms, success, error_message, context
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s, %s
                    )
                    RETURNING id;
                """

                db.cursor.execute(query, (
                    provider, model, usage_type, self.application, function_name,
                    input_tokens, output_tokens, total_tokens,
                    audio_duration_seconds, estimated_cost,
                    response_time_ms, success, error_message, context_json
                ))

                result = db.cursor.fetchone()
                db.conn.commit()

                record_id = result['id'] if result else None

                # Log summary
                cost_str = f"${estimated_cost:.6f}" if estimated_cost else "N/A"
                tokens_str = f"{total_tokens} tokens" if total_tokens else f"{audio_duration_seconds:.1f}s audio" if audio_duration_seconds else "N/A"
                print(f"[AITracker] {provider}/{model} | {usage_type} | {tokens_str} | {cost_str} | {response_time_ms}ms")

                return record_id

        except Exception as e:
            print(f"[AITracker] Error logging usage: {e}")
            return None

    def track_anthropic_response(
        self,
        model: str,
        usage_type: str,
        function_name: str,
        response: Any,
        start_time: float,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[int]:
        """
        Helper to track Anthropic API response.

        Args:
            model: Model used
            usage_type: Type of usage
            function_name: Source function
            response: Anthropic API response object
            start_time: time.time() from before the API call
            context: Additional context
        """
        response_time_ms = int((time.time() - start_time) * 1000)

        input_tokens = None
        output_tokens = None
        if hasattr(response, 'usage'):
            input_tokens = getattr(response.usage, 'input_tokens', None)
            output_tokens = getattr(response.usage, 'output_tokens', None)

        return self.log_usage(
            provider='anthropic',
            model=model,
            usage_type=usage_type,
            function_name=function_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            response_time_ms=response_time_ms,
            context=context
        )

    def track_openai_embedding(
        self,
        model: str,
        function_name: str,
        response: Any,
        start_time: float,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[int]:
        """Helper to track OpenAI embedding API call."""
        response_time_ms = int((time.time() - start_time) * 1000)

        input_tokens = None
        if hasattr(response, 'usage'):
            input_tokens = getattr(response.usage, 'prompt_tokens', None)

        return self.log_usage(
            provider='openai',
            model=model,
            usage_type='embeddings',
            function_name=function_name,
            input_tokens=input_tokens,
            response_time_ms=response_time_ms,
            context=context
        )

    def track_whisper(
        self,
        model: str,
        function_name: str,
        audio_duration_seconds: float,
        start_time: float,
        success: bool = True,
        error_message: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[int]:
        """Helper to track OpenAI Whisper transcription."""
        response_time_ms = int((time.time() - start_time) * 1000)

        return self.log_usage(
            provider='openai',
            model=model,
            usage_type='transcription',
            function_name=function_name,
            audio_duration_seconds=audio_duration_seconds,
            response_time_ms=response_time_ms,
            success=success,
            error_message=error_message,
            context=context
        )


# Singleton instance
_tracker: Optional[AIUsageTracker] = None


def get_ai_tracker(application: str = 'cupido_backend') -> AIUsageTracker:
    """Get singleton AIUsageTracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = AIUsageTracker(application)
    return _tracker
