#!/usr/bin/env python3
"""
Template Manager
Handles template configuration, storage, and script generation
"""

import os
import json
import uuid
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from google.cloud import firestore
from google.cloud import texttospeech
# Note: TTS service and video frame extraction functionality removed
# These imports are no longer available after cleanup

# Stub functions for missing dependencies
def get_audio_duration(audio_path: str) -> float:
    """Stub function - returns default duration"""
    return 5.0  # Default 5 seconds

class VideoFrameExtractor:
    """Stub class for video frame extraction"""
    def __init__(self):
        pass

def run_with_timeout(cmd, timeout=300, heartbeat_interval=10):
    """Stub function for running commands with timeout"""
    import subprocess
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr

class ProcessTimeoutError(Exception):
    """Stub exception for process timeout"""
    pass

# TTS Configuration
TTS_VOICE = "en-US-Neural2-F"
TTS_SPEED = 0.9

class GeneratedVideoModule:
    """Generated video module for creating question slides"""

    def __init__(self, tts_client=None):
        """Initialize the generated video module"""
        if tts_client is None:
            try:
                import os
                from google.cloud import texttospeech
                if os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'):
                    self.tts_client = texttospeech.TextToSpeechClient()
                else:
                    self.tts_client = None
            except Exception:
                self.tts_client = None
        else:
            self.tts_client = tts_client

    def generate_tts(self, text: str, path: str) -> float:
        if self.tts_client is None:
            raise RuntimeError("generate_tts should not be called; audio must be pre-generated upstream")
        from automations.custom_tts_service import synthesize_text
        return synthesize_text(
            self.tts_client,
            text=self._normalize_text(text),
            out_path=path,
            voice_name=TTS_VOICE,
            speaking_rate=TTS_SPEED,
            volume_gain_db=6.0,
        )

    # TTS generation removed from renderer - should only use pre-generated audio files

    def get_audio_duration(self, audio_path: str) -> float:
        """Get audio duration using ffprobe (delegates to tts_service)."""
        return get_audio_duration(audio_path)

    def render_text_to_png(self, text: str, box_config: Dict, out_path: str) -> None:
        """Render text to PNG using enhanced text renderer with full configurability"""
        try:
            import sys
            import os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'automations'))
            from enhanced_text_renderer import EnhancedTextRenderer
            
            # Use the enhanced text renderer
            renderer = EnhancedTextRenderer()
            renderer.render_text_to_png(self._normalize_text(text), box_config, out_path)
            
        except ImportError as e:
            # Do not silently fallback; surface the error to fail fast per project policy
            print(f"  ❌ Enhanced text renderer import failed: {e}")
            raise
        except Exception as e:
            print(f"  ❌ Text rendering failed: {e}")
            raise

    def create_question_slide(self, question_data: dict, background_path: str,
                             tmp_dir: str, output_dir: str,
                             explanation_start_override: float = None, 
                             template_data: dict = None,
                             audio_path: str = None,
                             explanation_audio_path: str = None,
                             question_index: int = 0) -> str:
        """Create a question slide using FFmpeg drawtext filters exactly as specified"""
        try:
            # Extract question data
            question = self._normalize_text(question_data.get('question', ''))
            answer_a = self._normalize_text(question_data.get('answer_a', ''))
            answer_b = self._normalize_text(question_data.get('answer_b', ''))
            answer_c = self._normalize_text(question_data.get('answer_c', ''))
            answer_d = self._normalize_text(question_data.get('answer_d', ''))
            correct_answer = question_data.get('correct_answer', 'A')
            explanation = question_data.get('explanation', '')
 
            # Prepare TTS audio files. If pre-generated audio is provided (pipeline slices), reuse it.
            question_audio = audio_path
            if not question_audio or not os.path.exists(question_audio):
                raise RuntimeError(f"Question audio missing or invalid: {question_audio}")
            question_tts_duration = self.get_audio_duration(question_audio)

            explanation_audio = explanation_audio_path or os.path.join(tmp_dir, "explanation_tts.mp3")
            if explanation_audio_path:
                if not os.path.exists(explanation_audio_path):
                    raise RuntimeError(f"Explanation audio missing: {explanation_audio_path}")
                explanation_tts_duration = self.get_audio_duration(explanation_audio_path)
            else:
                explanation_tts_duration = self.generate_tts(explanation, explanation_audio)
 
            # Get the actual answer text based on the correct answer letter
            if correct_answer == 'A':
                actual_answer = answer_a
            elif correct_answer == 'B':
                actual_answer = answer_b
            elif correct_answer == 'C':
                actual_answer = answer_c
            elif correct_answer == 'D':
                actual_answer = answer_d
            else:
                actual_answer = correct_answer  # Fallback if it's already the text
 
            # Use pre-generated upstream answer audio (includes "The correct answer is …")
            answer_audio = explanation_audio
            answer_tts_duration = self.get_audio_duration(answer_audio)

            # Constants for question overlay (Baseline-2 specs scaled to 1280x720)
            RECT = {'x': 133, 'y': 50, 'w': 1000, 'h': 117}
            STROKE = 2
            USABLE_W = RECT['w'] - 2 * STROKE
            USABLE_H = RECT['h'] - 2 * STROKE

            import logging
            logger = logging.getLogger(__name__)

            logger.info("  📝 Preparing question text wrapping with stroke/constraints...")
            wrapped_question, question_font_size, line_spacing = self._wrap_question_text(
                question,
                max_width=RECT['w'],
                max_height=RECT['h'],
                stroke_width=STROKE
            )

            logger.info(f"    • Wrapped question text: {repr(wrapped_question)}")
            logger.info(f"    • Question font size: {question_font_size}pt | line spacing: {line_spacing}px")

            question_text_file = os.path.join(tmp_dir, "question.txt")
            with open(question_text_file, "w", encoding="utf-8") as f:
                f.write(wrapped_question)

            # Wrap answer text to prevent bleeding
            logger.info("  📝 Preparing answer text wrapping...")
            wrapped_answer_a = self._wrap_answer_text(answer_a)
            wrapped_answer_b = self._wrap_answer_text(answer_b)
            wrapped_answer_c = self._wrap_answer_text(answer_c)
            wrapped_answer_d = self._wrap_answer_text(answer_d)
            
            # Get font sizes for each answer based on character count
            def get_font_size(text):
                if len(text) >= 50:
                    return 28
                elif len(text) >= 20:
                    return 32
                else:
                    return 48
            
            # Get font size for correct answer (larger base size: 72pt)
            def get_correct_answer_font_size(text):
                if len(text) >= 50:
                    return 42  # 72 * (28/48) = 42
                elif len(text) >= 20:
                    return 48  # 72 * (32/48) = 48
                else:
                    return 72  # Base size for short answers
            
            font_size_a = get_font_size(answer_a)
            font_size_b = get_font_size(answer_b)
            font_size_c = get_font_size(answer_c)
            font_size_d = get_font_size(answer_d)
            font_size_correct = get_correct_answer_font_size(actual_answer)
            
            # Wrap the correct answer text for multi-line support
            wrapped_correct_answer = self._wrap_answer_text(actual_answer)
            
            logger.info(f"    • Answer A: {wrapped_answer_a[0]} | {wrapped_answer_a[1]}")
            logger.info(f"    • Answer B: {wrapped_answer_b[0]} | {wrapped_answer_b[1]}")
            logger.info(f"    • Answer C: {wrapped_answer_c[0]} | {wrapped_answer_c[1]}")
            logger.info(f"    • Answer D: {wrapped_answer_d[0]} | {wrapped_answer_d[1]}")
            
            logger.info(
                "  📊 Answer line counts: A=%s, B=%s, C=%s, D=%s",
                '2' if wrapped_answer_a[1].strip() else '1',
                '2' if wrapped_answer_b[1].strip() else '1',
                '2' if wrapped_answer_c[1].strip() else '1',
                '2' if wrapped_answer_d[1].strip() else '1'
            )

            # Use timestamps from template data for proper synchronization
            timestamps = template_data.get('timestamps', {}) if template_data else {}
            question_start = timestamps.get('question_bar_settles', 1.0)  # Sync with question text appearance
            answer_a_start = timestamps.get('answer_a_appears', 5.0)
            answer_b_start = timestamps.get('answer_b_appears', 6.3)
            answer_c_start = timestamps.get('answer_c_appears', 8.1)
            answer_d_start = timestamps.get('answer_d_appears', 9.6)
            answers_fade_out = timestamps.get('answers_fade_out', 15.0)
            explanation_start = explanation_start_override if explanation_start_override is not None else timestamps.get('explanation_appears', 17.0)
            answers_fade_begin = timestamps.get('answers_fade_begin', 16.0)
            answers_fade_complete = timestamps.get('answers_fade_complete', answers_fade_begin + 1.0)
            correct_answer_start = timestamps.get('correct_answer_appears', 18.0)
            correct_answer_full = timestamps.get('correct_answer_fully_visible', correct_answer_start + 0.5)

            background_name = question_data.get('background_name', '') or ''
            sport_bg_2 = bool(background_name and 'sport-bg-2' in background_name.lower())
            if not sport_bg_2:
                sport_bg_2 = bool(background_path and 'sport-bg-2' in background_path.lower())
            if sport_bg_2:
                answers_fade_begin = max(0.0, answers_fade_begin - 1.5)
                answers_fade_complete = max(answers_fade_begin + 0.1, answers_fade_complete - 1.5)
                correct_answer_start = max(0.0, correct_answer_start - 1.5)
                correct_answer_full = max(correct_answer_start + 0.1, correct_answer_full - 1.5)

            fade_out_duration = max(0.25, answers_fade_complete - answers_fade_begin)
            correct_fade_duration = max(0.25, correct_answer_full - correct_answer_start)
            
            print(f"  ⏰ TTS Timing Synchronization:")
            print(f"    • Question TTS starts at: {question_start}s (syncs with question text)")
            print(f"    • Answer TTS starts at: {explanation_start}s (syncs with answer text)")
            print(f"    • Answer text appears at: A={answer_a_start}s, B={answer_b_start}s, C={answer_c_start}s, D={answer_d_start}s")
            
            # Use actual TTS end points as triggers (no calculations)
            question_end = question_start + question_tts_duration
            answer_end = explanation_start + answer_tts_duration
            
            # Use the actual answer TTS end point + 0.5s silence as video end trigger
            video_end_time = answer_end + 0.5
            
            print(f"  ⏰ TTS End Point Trigger:")
            print(f"    • answer_start = {explanation_start}s")
            print(f"    • answer_tts_duration = {answer_tts_duration:.2f}s")
            print(f"    • answer_end = {answer_end:.2f}s")
            print(f"    • video_end_time = {video_end_time:.2f}s (TTS end + 0.5s)")
            print(f"  🔍 DEBUG: Audio file path = {answer_audio}")
            print(f"  🔍 DEBUG: Audio file exists = {os.path.exists(answer_audio) if answer_audio else 'N/A'}")

            # Create FFmpeg command using drawtext filters exactly as specified
            logger.info(f"  🎬 Creating video with FFmpeg drawtext filters...")

            # Font path for Liberation Sans Bold
            font_path = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
            
            # Build drawtext filters - question text uses wrapped text file with stroke + shadow
            drawtext_filters = [
                # Scale background
                "scale=1280:720",
                f"drawtext=fontfile='{font_path}':textfile='{question_text_file}':fontcolor=white:fontsize={question_font_size}:borderw={STROKE}:bordercolor=black:shadowcolor=black@0.5:shadowx=2:shadowy=2:text_align=center:x={RECT['x']}+({RECT['w']}-tw)/2:y={RECT['y']}+({RECT['h']}-th)/2:line_spacing={line_spacing}:fix_bounds=1:alpha='if(lt(t,1),0,if(lt(t,1.5),(t-1)/0.5,1))':enable='gte(t,1)'"
            ]

            # Append existing answer drawtext filters (unchanged)
            answer_a_text_file = os.path.join(tmp_dir, "answer_a.txt")
            with open(answer_a_text_file, "w", encoding="utf-8") as f:
                f.write("\n".join(line for line in wrapped_answer_a if line.strip()))
            answer_b_text_file = os.path.join(tmp_dir, "answer_b.txt")
            with open(answer_b_text_file, "w", encoding="utf-8") as f:
                f.write("\n".join(line for line in wrapped_answer_b if line.strip()))
            answer_c_text_file = os.path.join(tmp_dir, "answer_c.txt")
            with open(answer_c_text_file, "w", encoding="utf-8") as f:
                f.write("\n".join(line for line in wrapped_answer_c if line.strip()))
            answer_d_text_file = os.path.join(tmp_dir, "answer_d.txt")
            with open(answer_d_text_file, "w", encoding="utf-8") as f:
                f.write("\n".join(line for line in wrapped_answer_d if line.strip()))
            correct_text_file = os.path.join(tmp_dir, "correct_answer.txt")
            with open(correct_text_file, "w", encoding="utf-8") as f:
                f.write("\n".join(line for line in wrapped_correct_answer if line.strip()))

            fade_out_expr = "if(lt(t,{fade_begin}),1, if(lt(t,{fade_end}),1-(t-{fade_begin})/{fade_duration},0))".format(
                fade_begin=f"{answers_fade_begin:.2f}",
                fade_end=f"{answers_fade_complete:.2f}",
                fade_duration=f"{fade_out_duration:.2f}"
            )

            def answer_alpha(start_time: float) -> str:
                return (
                    "if(lt(t,{start}),0,if(lt(t,{fade_in_end}),(t-{start})/0.5,{fade_out}))"
                ).format(
                    start=f"{start_time:.2f}",
                    fade_in_end=f"{(start_time + 0.5):.2f}",
                    fade_out=fade_out_expr
                )

            correct_alpha = (
                "if(lt(t,{start}),0,if(lt(t,{full}),(t-{start})/{duration},1))"
            ).format(
                start=f"{correct_answer_start:.2f}",
                full=f"{correct_answer_full:.2f}",
                duration=f"{correct_fade_duration:.2f}"
            )

            line_spacing_px = 4

            drawtext_filters.extend([
                f"drawtext=fontfile='{font_path}':textfile='{answer_a_text_file}':fontcolor=black:fontsize={font_size_a}:text_align=center:x=279+(308-text_w)/2:y=262+(131-th)/2:line_spacing={line_spacing_px}:alpha='{answer_alpha(answer_a_start)}':enable='gte(t,{answer_a_start:.2f})'",
                f"drawtext=fontfile='{font_path}':textfile='{answer_b_text_file}':fontcolor=black:fontsize={font_size_b}:text_align=center:x=775+(308-text_w)/2:y=259+(133-th)/2:line_spacing={line_spacing_px}:alpha='{answer_alpha(answer_b_start)}':enable='gte(t,{answer_b_start:.2f})'",
                f"drawtext=fontfile='{font_path}':textfile='{answer_c_text_file}':fontcolor=black:fontsize={font_size_c}:text_align=center:x=276+(293-text_w)/2:y=462+(120-th)/2:line_spacing={line_spacing_px}:alpha='{answer_alpha(answer_c_start)}':enable='gte(t,{answer_c_start:.2f})'",
                f"drawtext=fontfile='{font_path}':textfile='{answer_d_text_file}':fontcolor=black:fontsize={font_size_d}:text_align=center:x=775+(312-text_w)/2:y=463+(119-th)/2:line_spacing={line_spacing_px}:alpha='{answer_alpha(answer_d_start)}':enable='gte(t,{answer_d_start:.2f})'"
            ])

            drawtext_filters.append(
                f"drawtext=fontfile='{font_path}':textfile='{correct_text_file}':fontcolor=black:fontsize={font_size_correct}:borderw=3:bordercolor=white:text_align=center:x='(w-text_w)/2':y=372+(100-th)/2:line_spacing={line_spacing_px}:alpha='{correct_alpha}':enable='gte(t,{correct_answer_start:.2f})'"
            )

            # Audio mixing: keep background audible and prevent bleed
            # - Fade out background in last 0.5s
            # - Apply slight sidechain ducking during TTS
            # - Ensure total length trimmed to video_end_time

            # Output file
            output_path = os.path.join(output_dir, "generated_question_slide.mp4")

            # Get actual background video duration
            background_duration = self.get_audio_duration(background_path)
            extension_duration = max(0, video_end_time - background_duration)
            
            print(f"  ⏰ Background video duration: {background_duration:.2f}s")
            print(f"  ⏰ Extension needed: {extension_duration:.2f}s")
            
            # Build FIXED FFmpeg command - freeze background video to extend duration
            # Combine tpad and drawtext filters in complex filter chain
            # No ducking; only mute last 0.5s tail for true silence
            end_silence_start = max(0.0, video_end_time - 0.5)
            # Get audio volume settings from template
            settings = template_data.get('settings', {}) if template_data else {}
            bg_volume = settings.get('background_volume', 1.0)  # Background video volume
            tts_volume = settings.get('tts_volume', 2.25)  # TTS volume (+9dB from 0.8)
            music_volume = settings.get('music_volume', 0.2)  # Music volume (-6dB from 0.4)
            sfx_volume = settings.get('sfx_volume', 0.5)  # SFX volume (similar to music)
            
            # Randomly select music from all available audio assets (if enabled)
            music_enabled = template_data.get('input_data', {}).get('music_enabled', True) if template_data else True
            music_asset_id = None
            
            if music_enabled:
                music_asset_id = self._get_random_music_asset()
            
            # Build audio mixing based on available assets
            music_path = None
            has_music = False
            if music_asset_id:
                print(f"  🎵 Randomly selected music: {music_asset_id}")
                music_path = self._download_asset(music_asset_id, tmp_dir, "music")
                has_music = True

            fade_in_start = max(0.0, question_start - 5.0)
            fade_in_duration = 5.0
            fade_out_duration = max(0.5, min(2.0, answer_tts_duration))
            fade_out_start = max(fade_in_start + fade_in_duration, explanation_start)
            max_fade_out_start = max(0.0, video_end_time - fade_out_duration - 0.1)
            fade_out_start = min(fade_out_start, max_fade_out_start)

            if has_music:
                complex_filter = (
                    f"[0:v]tpad=stop_mode=clone:stop_duration={extension_duration},{','.join(drawtext_filters)}[bg_extended];"
                    f"[0:a]volume={bg_volume},highpass=f=200,afade=out:st={end_silence_start}:d=0.5[bg_a];"
                    f"[1:a]pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1,volume={tts_volume},adelay={(question_start * 1000):.0f}|{(question_start * 1000):.0f}[q_delayed];"
                    f"[2:a]pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1,volume={tts_volume},adelay={(explanation_start * 1000):.0f}|{(explanation_start * 1000):.0f}[exp_delayed];"
                    f"[3:a]volume={music_volume},aloop=loop=-1:size=2e+09,atrim=0:{video_end_time},asetpts=N/SR/TB,afade=in:st={fade_in_start:.3f}:d={fade_in_duration:.3f},afade=out:st={fade_out_start:.3f}:d={fade_out_duration:.3f}[music_loop];"
                    f"[bg_a][music_loop][q_delayed][exp_delayed]amix=inputs=4:duration=longest,volume=1.0[out_a]"
                )

                cmd = [
                    "ffmpeg", "-y",
                    "-i", background_path,  # Video with ambience
                    "-i", question_audio,
                    "-i", answer_audio,
                    "-i", music_path,
                    "-filter_complex", complex_filter,
                    "-map", "[bg_extended]",
                    "-map", "[out_a]",
                    "-c:v", "libx264",
                    "-c:a", "aac",
                    "-pix_fmt", "yuv420p",
                    "-t", str(video_end_time),
                    output_path
                ]
            else:
                # No music - create silent audio track
                complex_filter = (
                    f"[0:v]tpad=stop_mode=clone:stop_duration={extension_duration},{','.join(drawtext_filters)}[bg_extended];"
                    f"[0:a]volume={bg_volume},highpass=f=200,afade=out:st={end_silence_start}:d=0.5[bg_a];"
                    f"[1:a]pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1,volume={tts_volume},adelay={(question_start * 1000):.0f}|{(question_start * 1000):.0f}[q_delayed];"
                    f"[2:a]pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1,volume={tts_volume},adelay={(explanation_start * 1000):.0f}|{(explanation_start * 1000):.0f}[exp_delayed];"
                    f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={video_end_time}[silence];"
                    f"[bg_a][silence][q_delayed][exp_delayed]amix=inputs=4:duration=longest,volume=1.0[out_a]"
                )

                cmd = [
                    "ffmpeg", "-y",
                    "-i", background_path,  # Video with ambience
                    "-i", question_audio,
                    "-i", answer_audio,
                    "-f", "lavfi",
                    "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={video_end_time}",
                    "-filter_complex", complex_filter,
                    "-map", "[bg_extended]",
                    "-map", "[out_a]",
                    "-c:v", "libx264",
                    "-c:a", "aac",
                    "-pix_fmt", "yuv420p",
                    "-t", str(video_end_time),
                    output_path
                ]
            
            print(f"  🔊 Using question_audio: {question_audio}")
            print(f"  🔊 Using answer_audio:   {answer_audio}")
            print(f"  🔊 Detected question_tts_duration: {question_tts_duration:.2f}s")
            print(f"  🔊 Detected answer_tts_duration:   {answer_tts_duration:.2f}s")
            print(f"  🔧 FFmpeg filter_complex: {complex_filter}")
            print(f"  🎬 Running FFmpeg command...")
            print(f"  📊 Audio mixing: Background={bg_volume}, TTS={tts_volume}, Music={music_volume}, SFX={sfx_volume}")
            
            try:
                return_code, stdout, stderr = run_with_timeout(cmd, timeout=300, heartbeat_interval=10)
                if return_code != 0:
                    print(f"  ❌ FFmpeg failed: {stderr}")
                    raise RuntimeError(f"FFmpeg failed: {stderr}")
            except ProcessTimeoutError as e:
                print(f"  ⏰ Render timed out: {e}")
                raise
            
            print(f"  ✅ Question slide generated: {output_path}")
            return output_path

        except Exception as e:
            print(f"  ❌ Failed to create generated question slide: {e}")
            raise

    def _get_random_music_asset(self) -> str:
        """Get a random music asset from all available audio assets."""
        try:
            import requests
            import random
            
            print(f"  🎲 Starting random music selection...")
            
            # Get all recent uploads
            response = requests.get('http://localhost:6001/api/recent-uploads')
            print(f"  🎲 API response status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"  🎲 API response data keys: {list(data.keys())}")
                
                if data.get('success'):
                    # Filter for audio assets
                    audio_assets = [upload for upload in data['uploads'] if upload.get('type') == 'audio']
                    print(f"  🎲 Found {len(audio_assets)} audio assets")
                    
                    if audio_assets:
                        # Randomly select one
                        selected_asset = random.choice(audio_assets)
                        print(f"  🎲 Random selection from {len(audio_assets)} music files")
                        print(f"  🎲 Selected asset: {selected_asset['name']} (ID: {selected_asset['id']})")
                        return selected_asset['id']
                    else:
                        print(f"  ⚠️ No audio assets found for random selection")
                        return None
                else:
                    print(f"  ❌ Failed to get recent uploads: {data.get('error')}")
                    return None
            else:
                print(f"  ❌ API request failed: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"  ❌ Failed to get random music asset: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _download_asset(self, asset_id: str, tmp_dir: str, asset_type: str) -> str:
        """Download an asset from GCS to temporary directory."""
        try:
            print(f"  📥 Starting download of {asset_type} asset: {asset_id}")
            
            from automations.apple_clean_gcs import AppleCleanGCSManager
            
            # Initialize GCS manager
            gcs_manager = AppleCleanGCSManager("dev")
            print(f"  📥 GCS manager initialized")
            
            # Download asset
            local_path = os.path.join(tmp_dir, f"{asset_type}_{asset_id}.mp3")
            print(f"  📥 Downloading to: {local_path}")
            
            success = gcs_manager.download_asset(asset_id, local_path)
            print(f"  📥 Download result: {success}")
            
            if success and os.path.exists(local_path):
                print(f"  ✅ Downloaded {asset_type} asset: {asset_id}")
                return local_path
            else:
                print(f"  ❌ Download failed or file not found: {local_path}")
                raise Exception(f"Download failed for asset {asset_id}")
            
        except Exception as e:
            print(f"  ❌ Failed to download {asset_type} asset {asset_id}: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _escape_drawtext(self, text: str) -> str:
        """Escape text for safe use in FFmpeg drawtext 'text=' option.
        Escapes backslashes, colons, apostrophes, double quotes, and percent signs.
        """
        if text is None:
            return ""
        escaped = text.replace("\\", "\\\\")
        escaped = escaped.replace(":", "\\:")
        escaped = escaped.replace("'", "\\'")  # Escape apostrophes
        escaped = escaped.replace('"', '\\"')  # Escape double quotes
        escaped = escaped.replace("%", "\\%")
        return escaped

    def _normalize_text(self, s: str) -> str:
        """Normalize doubled quotes and stray punctuation for clean TTS and drawtext."""
        if not s:
            return s
        s = s.replace("''", "'").replace('""', '"')
        s = s.replace("\"'", "'").replace("'\"", "'")
        s = ' '.join(s.split())
        return s

    def _has_audio_stream(self, media_path: str) -> bool:
        """Return True if the media file has at least one audio stream."""
        try:
            try:
                return_code, stdout, stderr = run_with_timeout([
                    "ffprobe", "-v", "error",
                    "-select_streams", "a:0",
                    "-show_entries", "stream=index",
                    "-of", "csv=p=0",
                    media_path
                ], timeout=15, heartbeat_interval=5)
                return return_code == 0 and stdout.strip() != ""
            except ProcessTimeoutError:
                return False
        except Exception:
            return False

    def _measure_text_with_stroke(self, text: str, font, stroke_width: int = 2):
        """Measure text dimensions including stroke width using Pillow."""
        try:
            from PIL import Image, ImageDraw
            img = Image.new("L", (4096, 1024), 0)
            d = ImageDraw.Draw(img)
            bbox = d.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            return len(text) * 28, 56

    def _wrap_question_text(self, text: str, max_width: int = 1000, max_height: int = 117, stroke_width: int = 2):
        """Wrap question text to fit within rectangle, returning (wrapped_text, font_size, line_spacing)."""
        try:
            from PIL import ImageFont
            font_path = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
        except Exception:
            return text, 56, 8

        words = text.split()
        if not words:
            return "", 56, 8

        usable_width = max_width - 2 * stroke_width
        usable_height = max_height - 2 * stroke_width

        font_size = 56
        min_font_size = 28

        while font_size >= min_font_size:
            try:
                font = ImageFont.truetype(font_path, font_size)
            except Exception:
                break

            lines = []
            current_line = []

            for word in words:
                test_line = " ".join(current_line + [word])
                line_width, line_height = self._measure_text_with_stroke(test_line, font, stroke_width)

                if line_width <= usable_width:
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(" ".join(current_line))
                        current_line = [word]
                    else:
                        lines.append(word)

            if current_line:
                lines.append(" ".join(current_line))

            if lines:
                _, line_height = self._measure_text_with_stroke(lines[0], font, stroke_width)
                line_spacing = int(0.15 * font_size)
                total_height = len(lines) * line_height + (len(lines) - 1) * line_spacing

                if total_height <= usable_height:
                    wrapped_text = "\n".join(lines)
                    return wrapped_text, font_size, line_spacing

            font_size -= 2

        try:
            font = ImageFont.truetype(font_path, min_font_size)
            _, line_height = self._measure_text_with_stroke(text, font, stroke_width)
            line_spacing = int(0.15 * min_font_size)

            if line_height > usable_height:
                for i in range(len(text), 0, -1):
                    test_text = text[:i] + "..."
                    _, test_height = self._measure_text_with_stroke(test_text, font, stroke_width)
                    if test_height <= usable_height:
                        return test_text, min_font_size, line_spacing
                return "...", min_font_size, line_spacing

            return text, min_font_size, line_spacing
        except Exception:
            return text, min_font_size, 8

    def _wrap_answer_text(self, text: str, max_width: int = 180) -> List[str]:
        """Wrap answer text into up to 2 lines with balanced wrapping for answer boxes.
        Uses conservative width to fit within the white answer boxes.
        Scales font based on character count: 48pt for ≤19 chars, 32pt for 20-49 chars, 28pt for ≥50 chars.
        """
        try:
            from PIL import ImageFont
            font_path = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
            
            # Dynamic font sizing based on character count
            if len(text) >= 50:
                font_size = 28  # Extra small for very long text
                avg_char_px = 14  # Smaller for 28pt font
            elif len(text) >= 20:
                font_size = 32  # Scaled down for longer text
                avg_char_px = 16  # Smaller for 32pt font
            else:
                font_size = 48  # Original size for shorter text
                avg_char_px = 24  # Larger for 48pt font
                
            font = ImageFont.truetype(font_path, font_size)
        except Exception:
            # Fallback to simple estimate if PIL/font missing
            if len(text) >= 50:
                avg_char_px = 14  # Smaller for 28pt font
            elif len(text) >= 20:
                avg_char_px = 16  # Smaller for 32pt font
            else:
                avg_char_px = 24  # Larger for 48pt font
            return self._naive_wrap(text, max_width, avg_char_px)

        words = text.split()
        if not words:
            return ["", ""]

        def line_width_px(line: str) -> int:
            try:
                return int(font.getlength(line))
            except Exception:
                return int(font.getsize(line)[0])

        # Try to create balanced lines - avoid orphan words
        if len(words) <= 2:
            # Check if even 2 words fit on one line
            full_text = " ".join(words)
            if line_width_px(full_text) <= max_width:
                return [full_text, ""]
            else:
                # Even 2 words are too long, split them
                return [words[0], words[1] if len(words) > 1 else ""]
        
        # Find the best split point for balanced lines
        best_split = 0
        best_balance = float('inf')
        
        for i in range(1, len(words)):
            line1 = " ".join(words[:i])
            line2 = " ".join(words[i:])
            
            # Check if both lines fit
            if line_width_px(line1) <= max_width and line_width_px(line2) <= max_width:
                # Calculate balance (avoid orphan lines)
                line1_len = len(line1)
                line2_len = len(line2)
                
                # Prefer splits that avoid very short second lines (orphans)
                if line2_len < line1_len * 0.5:
                    continue  # Skip this split - creates orphan
                
                # Calculate balance score (lower is better)
                balance = abs(line1_len - line2_len)
                if balance < best_balance:
                    best_balance = balance
                    best_split = i
        
        if best_split > 0:
            line1 = " ".join(words[:best_split])
            line2 = " ".join(words[best_split:])
        else:
            # Fallback: put most words on first line, rest on second
            mid_point = len(words) // 2
            line1 = " ".join(words[:mid_point])
            line2 = " ".join(words[mid_point:])
        
        return [line1, line2]

    def _naive_wrap(self, text: str, max_width: int, avg_char_px: int) -> List[str]:
        words = text.split()
        current = ""
        lines: List[str] = []
        for w in words:
            trial = (current + (" " if current else "") + w)
            if len(trial) * avg_char_px <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                    current = w
                else:
                    lines.append(w)
        if current:
            lines.append(current)
        while len(lines) < 2:
            lines.append("")
        return lines[:2]


# Factory function for easy integration
def create_generated_module(tts_client=None):
    """Create a GeneratedVideoModule instance"""
    return GeneratedVideoModule(tts_client)


class TemplateManager:
    """Manages video template configurations and script generation"""
    
    def __init__(self):
        """Initialize template manager"""
        self.firestore_client = firestore.Client()
        
        # Use environment-aware collection names
        environment = 'dev'
        self.templates_collection = self.firestore_client.collection(f"{environment}_templates")
        self.assets_collection = self.firestore_client.collection(f"{environment}_assets")
        self.frame_extractor = VideoFrameExtractor()
        
    def create_template(self, name: str, description: str, video_dimensions: Tuple[int, int] = (1920, 1080), channel_id: str = None) -> str:
        """Create a new template configuration"""
        template_id = f"template_{uuid.uuid4().hex[:8]}"
        
        # Default text positions (similar to current SlideBoxes)
        default_config = {
            "id": template_id,
            "name": name,
            "description": description,
            "channel_id": channel_id,
            "video_dimensions": {
                "width": video_dimensions[0],
                "height": video_dimensions[1]
            },
            "text_boxes": {
                "question": {
                    "x": 100, "y": 150, "width": 800, "height": 100,
                    "font_size": 48, "font_weight": "bold",
                    "text_color": "#FFFFFF", "background_color": "#FF0000",
                    "padding": 10, "alignment": "center"
                },
                "answer_a": {
                    "x": 100, "y": 300, "width": 400, "height": 80,
                    "font_size": 36, "font_weight": "normal",
                    "text_color": "#000000", "background_color": "#FFFFFF",
                    "padding": 8, "alignment": "center"
                },
                "answer_b": {
                    "x": 520, "y": 300, "width": 400, "height": 80,
                    "font_size": 36, "font_weight": "normal",
                    "text_color": "#000000", "background_color": "#FFFFFF",
                    "padding": 8, "alignment": "center"
                },
                "answer_c": {
                    "x": 100, "y": 400, "width": 400, "height": 80,
                    "font_size": 36, "font_weight": "normal",
                    "text_color": "#000000", "background_color": "#FFFFFF",
                    "padding": 8, "alignment": "center"
                },
                "answer_d": {
                    "x": 520, "y": 400, "width": 400, "height": 80,
                    "font_size": 36, "font_weight": "normal",
                    "text_color": "#000000", "background_color": "#FFFFFF",
                    "padding": 8, "alignment": "center"
                },
                "explanation": {
                    "x": 100, "y": 500, "width": 800, "height": 100,
                    "font_size": 42, "font_weight": "bold",
                    "text_color": "#FFFFFF", "background_color": "#00FF00",
                    "padding": 10, "alignment": "center"
                }
            },
            "timestamps": {
                "question_bar_settles": 1.0,
                "answer_a_appears": 5.0,
                "answer_b_appears": 6.0,
                "answer_c_appears": 8.0,
                "answer_d_appears": 9.0,
                "answers_fade_out": 17.0,
                "explanation_appears": 18.0
            },
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
            "status": "active"
        }
        
        self.templates_collection.document(template_id).set(default_config)
        print(f"✅ Template created: {name} (ID: {template_id})")
        return template_id
    
    def get_template(self, template_id: str) -> Optional[Dict]:
        """Get template configuration"""
        doc = self.templates_collection.document(template_id).get()
        if doc.exists:
            return doc.to_dict()
        return None
    
    def get_all_templates(self) -> List[Dict]:
        """Get all templates"""
        templates = []
        docs = self.templates_collection.where("status", "==", "active").stream()
        for doc in docs:
            template_data = doc.to_dict()
            templates.append(template_data)
        return templates
    
    def update_template(self, template_id: str, updates: Dict) -> bool:
        """Update template configuration"""
        try:
            updates["updated_at"] = firestore.SERVER_TIMESTAMP
            self.templates_collection.document(template_id).update(updates)
            print(f"✅ Template updated: {template_id}")
            return True
        except Exception as e:
            print(f"❌ Failed to update template: {e}")
            return False
    
    def delete_template(self, template_id: str) -> bool:
        """Delete template"""
        try:
            self.templates_collection.document(template_id).delete()
            print(f"✅ Template deleted: {template_id}")
            return True
        except Exception as e:
            print(f"❌ Failed to delete template: {e}")
            return False
    
    def generate_script_from_template(self, template_id: str) -> str:
        """Generate Python script from template configuration"""
        template = self.get_template(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")
        
        # Generate the script content
