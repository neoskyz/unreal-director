// REFERENCE ONLY: Starseal's recording mode (SGGameModeRecord.cpp), lightly annotated. Not a library: it is a slice of
// the game mode class (ASGGameMode), so it will not compile on its own. What to take from it:
//   - FApp::SetUseFixedTimeStep + SetFixedDeltaTime(1/fps): the game advances exactly one frame per screenshot, however
//     long the PNG takes to write. No screen recording permission, no dropped frames, deterministic with a fixed seed.
//   - One FScreenshotRequest per frame into <dir>/frames/frame_%06d.png.
//   - Every sound the game plays is also logged as a JSON line (t, kind, name, vol, pitch, fade, action) and mixed
//     offline by scripts/qc/make_video.py, so the video has sound although the game ran with -nosound.
//   - Segments start / stop on game events (RecordMark("state:Battle")...): the SEGMENT TABLE below is Starseal's and
//     must be replaced with your own states. The ambience / wind loop names are Starseal's too.
//   - -SGFrameLog prints SG_RECFRAME per frame, to line frame numbers up with other per-frame logs when hunting a
//     one-frame glitch (scripts/qc/presence_check.py finds such frames).
// Driven by scripts/native/record_native.py: -SGRecord=<abs dir> -SGSegment=<name> [-SGRecordFps=30] -SGAutoPlay.

#include "GameFramework/PlayerController.h"
#include "HAL/PlatformMisc.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "HAL/FileManager.h"
#include "SGGameMode.h"
#include "SGUtil.h"
#include "UnrealClient.h"

namespace
{
struct FSegment
{
	const TCHAR* Name;
	const TCHAR* Start;  // RecordMark event that starts recording
	const TCHAR* Stop;   // RecordMark event that stops it (after StopDelay seconds)
	float StopDelay;
	float MaxSeconds;
};

// ---- STARSEAL-SPECIFIC: replace with your own segments and the events your game mode reports ----
const FSegment Segments[] = {
	{TEXT("full"), TEXT("state:Title"), TEXT("state:Ending"), 14.f, 600.f},
	{TEXT("garage_launch"), TEXT("state:Garage"), TEXT("state:Explore"), 3.f, 60.f},
	{TEXT("explore"), TEXT("state:Explore"), TEXT("state:Battle"), 0.5f, 60.f},
	{TEXT("capture"), TEXT("state:Battle"), TEXT("state:Explore"), 1.0f, 90.f},
	{TEXT("walk"), TEXT("Explore:captured"), TEXT("state:Battle"), 0.3f, 40.f},  // walking to the second spirit
	{TEXT("boss"), TEXT("state:BossIntro"), TEXT("state:Ending"), 0.5f, 300.f},
	{TEXT("ending"), TEXT("state:Ending"), TEXT("state:Ending"), 14.f, 30.f},
};

const FSegment* FindSegment(const FString& Name)
{
	for (const FSegment& S : Segments)
		if (Name == S.Name) return &S;
	return nullptr;
}
}

void ASGGameMode::InitRecord()
{
	if (!FParse::Value(FCommandLine::Get(), TEXT("SGRecord="), RecDir)) return;
	RecSegment = TEXT("full");
	FParse::Value(FCommandLine::Get(), TEXT("SGSegment="), RecSegment);
	FParse::Value(FCommandLine::Get(), TEXT("SGRecordFps="), RecFps);
	RecFps = FMath::Clamp(RecFps, 10, 120);
	if (!FindSegment(RecSegment))
	{
		SG::Log(FString::Printf(TEXT("SG_FAIL unknown segment %s"), *RecSegment));
		RecSegment = TEXT("full");
	}
	IFileManager::Get().MakeDirectory(*FPaths::Combine(RecDir, TEXT("frames")), true);
	// fixed time step: the game advances exactly 1/fps per frame however long the PNG takes to write
	FApp::SetUseFixedTimeStep(true);
	FApp::SetFixedDeltaTime(1.0 / RecFps);
	SG::Log(FString::Printf(TEXT("SG_RECORD init dir=%s segment=%s fps=%d"), *RecDir, *RecSegment, RecFps));
}

void ASGGameMode::RecordMark(const FString& Event)
{
	if (!IsRecordMode() || bRecordDone) return;
	const FSegment* Seg = FindSegment(RecSegment);
	if (!Seg) return;
	if (!bRecording && Event == Seg->Start)
	{
		bRecording = true;
		RecFrame = 0;
		RecAudio.Reset();
		SG::Log(FString::Printf(TEXT("SG_RECORD start %s t=%.1f"), *Event, TotalTime));
		// what is already playing when the segment starts
		if (!MusicName.IsEmpty()) RecordAudio(TEXT("music"), MusicName, MusicVol, MusicPitch, 0.f);
		if (bAmbienceOn)
		{
			RecordAudio(TEXT("loop"), TEXT("asteroid_ambience_loop"), 0.35f, 1.f, 0.f, TEXT("start"));
			RecordAudio(TEXT("loop"), TEXT("cloud_wind_loop"), WindVol, WindPitch, 0.f, TEXT("start"));
		}
		// a segment whose start and stop are the same event (ending) arms the stop timer right away
		if (Event == Seg->Stop) RecStopIn = Seg->StopDelay;
		return;
	}
	if (bRecording && RecStopIn < 0.f && Event == Seg->Stop)
	{
		RecStopIn = Seg->StopDelay;
		SG::Log(FString::Printf(TEXT("SG_RECORD stop-armed %s"), *Event));
	}
}

void ASGGameMode::RecordAudio(const FString& Kind, const FString& Name, float Vol, float Pitch, float Fade, const TCHAR* Action)
{
	if (!bRecording) return;
	const double T = double(RecFrame) / RecFps;
	FString L = FString::Printf(TEXT("{\"t\": %.4f, \"kind\": \"%s\", \"name\": \"%s\", \"vol\": %.4f, \"pitch\": %.4f, \"fade\": %.3f"), T, *Kind, *Name, Vol,
		Pitch, Fade);
	if (Action) L += FString::Printf(TEXT(", \"action\": \"%s\""), Action);
	L += TEXT("}");
	RecAudio.Add(L);
}

void ASGGameMode::TickRecord(float Dt)
{
	if (!IsRecordMode()) return;
	if (APlayerController* P = PC()) P->SetShowMouseCursor(SG::NoMouse());  // unattended: leave the system cursor alone (F-029)
	if (RecExitIn >= 0.f)
	{
		// let the last PNGs finish writing, then quit
		if ((RecExitIn -= Dt) < 0.f) FPlatformMisc::RequestExit(false, TEXT("SGRecord"));
		return;
	}
	if (!bRecording) return;
	const FSegment* Seg = FindSegment(RecSegment);
	if (bAmbienceOn && (RecLoopTimer -= Dt) <= 0.f)
	{
		RecLoopTimer = 0.1f;
		RecordAudio(TEXT("loopvol"), TEXT("cloud_wind_loop"), WindVol, WindPitch, 0.f);
	}
	FScreenshotRequest::RequestScreenshot(FPaths::Combine(RecDir, TEXT("frames"), FString::Printf(TEXT("frame_%06d.png"), RecFrame)), true, false);
	if (FParse::Param(FCommandLine::Get(), TEXT("SGFrameLog"))) SG::Log(FString::Printf(TEXT("SG_RECFRAME %d t=%.3f"), RecFrame, GetWorld()->GetTimeSeconds()));
	++RecFrame;
	const float RecTime = float(RecFrame) / RecFps;
	if (RecStopIn >= 0.f && (RecStopIn -= 1.f / RecFps) < 0.f) StopRecord();  // armed by the stop event
	else if (Seg && RecTime > Seg->MaxSeconds) StopRecord();
}

void ASGGameMode::StopRecord()
{
	if (!bRecording) return;
	bRecording = false;
	bRecordDone = true;
	FFileHelper::SaveStringArrayToFile(RecAudio, *FPaths::Combine(RecDir, TEXT("audio_events.jsonl")));
	const FString Meta = FString::Printf(TEXT("{\"fps\": %d, \"segment\": \"%s\", \"frames\": %d}"), RecFps, *RecSegment, RecFrame);
	FFileHelper::SaveStringToFile(Meta, *FPaths::Combine(RecDir, TEXT("record.json")));
	SG::Log(FString::Printf(TEXT("SG_RECORD done frames=%d seconds=%.1f audio_events=%d"), RecFrame, float(RecFrame) / RecFps, RecAudio.Num()));
	RecExitIn = 1.5f;
}
