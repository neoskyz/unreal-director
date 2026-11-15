// REFERENCE ONLY: the shape of Starseal's autoplay bot (SGGameMode*.cpp), reduced to the parts any game can copy.
// The bot itself (walk to the next creature, pick a move, throw the seal) is game logic and is not shown.
// Everything it reports goes through SG::Log with the fixed prefixes the scripts parse (guides/log-protocol.md).

// ---- State changes: one SG_STATE line, and the frame-rate summary of the state that just ended -----------------------
void ASGGameMode::SetState(ESGState NewState, const FString& Detail)
{
	if (State != ESGState::Boot && FpsTime > 0.5)
	{
		SG::Log(FString::Printf(TEXT("SG_FPS %s avg=%.1f worst=%.1f frames=%d"), StateName(State), FpsFrames / FpsTime,
			FpsWorst > 0.f ? 1.f / FpsWorst : 0.f, FpsFrames));
	}
	FpsTime = 0.0;
	FpsFrames = 0;
	FpsWorst = 0.f;
	State = NewState;
	StateTime = 0.f;
	SG::Log(FString::Printf(TEXT("SG_STATE %s%s%s t=%.1f"), StateName(NewState), Detail.IsEmpty() ? TEXT("") : TEXT(" "), *Detail, TotalTime));
	LastProgress = TotalTime;  // the watchdog below counts from here (battle events reset it too)
	RecordMark(FString(TEXT("state:")) + StateName(NewState));  // recording mode (RecordMode.cpp)
}

// ---- Screenshots by name, once each (the web test takes the page screenshot when it sees SG_SHOT) --------------------
void ASGGameMode::ShotOnce(const FString& Name)
{
	if (IsRecordMode()) return;  // every frame is a screenshot already
	if (ShotsTaken.Contains(Name)) return;
	ShotsTaken.Add(Name);
	SG::Shot(Name);
}

// ---- The bot's tick: special check modes first, then the normal play-through ----------------------------------------
void ASGGameMode::TickAutoPlay(float Dt)
{
	TotalTime += Dt;
	if (!SG::IsAutoPlay()) return;
	// "Check modes" replace the play-through once the player is in the world: they walk a list of places / screens,
	// take one picture each, then print SG_DONE <mode>. Starseal had a path patrol (stand on every path every 3.5 m,
	// both ways, picture each stop; first log any prop standing on a path as SG_WAY_BAD) and a layout check (every
	// button and card filled with its longest text). Each one answers "is anything wrong ANYWHERE", which a single
	// play-through never visits.
	if (SG::PatrolCheck() && State == ESGState::Explore && !bPatrolDone) { TickPatrol(Dt); return; }
	if (SG::LayoutCheck() && State == ESGState::Explore && !bLayoutDone) { TickLayoutCheck(Dt); return; }

	// ... the play-through: dialogs are read (a picture) and closed, cards are pictured and clicked on, etc. ...
	if (bShowNotice)
	{
		if (NoticeAge > 1.3f) ShotOnce(TEXT("01n_dialog"));
		if (NoticeAge > 1.8f) CloseNotice();
		return;
	}

	// Watchdog: no state change and no battle event for 120 s = stuck. Picture, SG_FAIL, non-zero exit code.
	// (60 s was too tight at --speed 1: the longest legitimate walk took 60 s and tripped it one run in three.)
	if (!bDoneLogged && TotalTime - LastProgress > 120.f && State != ESGState::Ending)
	{
		bDoneLogged = true;
		SG::Shot(TEXT("stuck"));
		SG::Log(FString::Printf(TEXT("SG_FAIL stuck state=%d t=%.1f"), static_cast<int>(State), TotalTime));
		if (SG::AutoPlayExit()) FPlatformMisc::RequestExitWithStatus(false, 3, TEXT("SGStuck"));
		return;
	}
	if (TotalTime > 900.f && !bDoneLogged)
	{
		bDoneLogged = true;
		SG::Log(FString::Printf(TEXT("SG_FAIL timeout state=%d"), static_cast<int>(State)));
	}

	// ... at the end of the run (Ending state reached and shown):
	//   SG::DumpPackages();   // anything the scripts must read goes BEFORE SG_DONE: they stop reading at that line
	//   SG::Log(FString::Printf(TEXT("SG_DONE captures=%d battles=%d defeats=%d time=%.1f"), ...));
	//   if (SG::AutoPlayExit()) FPlatformMisc::RequestExit(false, TEXT("SGDone"));
}

// ---- Per-frame diagnostics behind -SGFrameLog (only when hunting a one-frame glitch) ---------------------------------
// Starseal's hero vanished for one frame at each walking-pose change. The log printed, per frame, which texture was
// shown and whether it was still compiling / resident, plus the card and camera positions:
//   SG_HEROFRAME T_Hero_Walk2 compiling=0 res=1 resident=1/1
//   SG_HEROTICK t=12.345 vis=1 hid=0 card=(..) cam=(..) actor=(..) tex=0 frame=2
// Lined up with SG_RECFRAME <n> from the recording mode, that tells "texture not ready" from "camera and character out
// of step on that frame". The cure for the first cause was to load and keep every swappable picture resident before
// its first use (prewarm), instead of binding it on the frame it is needed.
