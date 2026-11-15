// REFERENCE ONLY: excerpt from Starseal (SGUtil.cpp), not a library. Copy what you need into your game module and
// rename the SG prefix. The test scripts in scripts/ read the log lines these functions print (guides/log-protocol.md).
//
// One switch, two spellings: a command-line flag for native runs (-SGPatrol) and a URL query parameter for the Wasm
// build (?sgpatrol=1). The browser tests can then drive the packaged Shipping game without a special build.
#include "CoreMinimal.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "UnrealClient.h"

#include <cstdio>

#if PLATFORM_WASM
#include <emscripten/console.h>
#include <emscripten/emscripten.h>
#include <emscripten/threading.h>
#endif

DECLARE_LOG_CATEGORY_EXTERN(LogMyGame, Log, All);  // (declare / define it in your module as usual)

namespace SG
{
// One line to the UE log AND to stdout (native) / the browser console (Wasm), also in Shipping builds.
// Native: printf + fflush, because the UE log on stdout is buffered behind a pipe and a test script waits on these lines.
// Wasm: emscripten_out lands in the page console, where Playwright's page.on("console") sees it.
void Log(const FString& Line)
{
	UE_LOG(LogMyGame, Display, TEXT("%s"), *Line);
#if PLATFORM_WASM
	emscripten_out(TCHAR_TO_UTF8(*Line));
#else
	std::printf("%s\n", TCHAR_TO_UTF8(*Line));
	std::fflush(stdout);
#endif
}

// -Name on the command line, or ?name in the page URL (Wasm). Read once, cached by the callers.
static bool UrlOrCmd(const TCHAR* Cmd, const char* Url)
{
	bool bOn = FParse::Param(FCommandLine::Get(), Cmd);
#if PLATFORM_WASM
	if (!bOn)
	{
		bOn = MAIN_THREAD_EM_ASM_INT({
			try { return (new URLSearchParams(location.search)).has(UTF8ToString($0)) ? 1 : 0; } catch (e) { return 0; }
		}, Url) != 0;
	}
#else
	(void)Url;
#endif
	return bOn;
}

bool IsAutoPlay()
{
	static int Cached = -1;
	if (Cached < 0) Cached = UrlOrCmd(TEXT("SGAutoPlay"), "sgautoplay") ? 1 : 0;
	return Cached == 1;
}

// Unattended runs must never capture, lock, hide or move the system mouse: a human is using the machine while the agent
// tests (see NoMouse.cpp for what this turns off).
bool NoMouse()
{
	static int Cached = -1;
	if (Cached < 0)
	{
		const TCHAR* C = FCommandLine::Get();
		Cached = (IsAutoPlay() || FParse::Param(C, TEXT("RenderOffscreen")) || FParse::Param(C, TEXT("SGNoMouse")) ||
				  FCString::Stristr(C, TEXT("-SGRecord=")) != nullptr) ? 1 : 0;
	}
	return Cached == 1;
}

// Quit after the run (native regression scripts wait for the process to end).
bool AutoPlayExit() { return FParse::Param(FCommandLine::Get(), TEXT("SGAutoPlayExit")); }

// Event playback speed (-SGSpeed=2 / ?sgspeed=2): the autoplay bot and battle animations run faster for regressions.
// Use 1 when checking continuous action: at 2x you only ever see half the frames.
float Speed()
{
	static float Cached = -1.f;
	if (Cached < 0.f)
	{
		float S = 1.f;
		FParse::Value(FCommandLine::Get(), TEXT("SGSpeed="), S);
#if PLATFORM_WASM
		const double UrlSpeed = MAIN_THREAD_EM_ASM_DOUBLE({
			try { var v = parseFloat((new URLSearchParams(location.search)).get('sgspeed')); return Number.isFinite(v) ? v : 0; } catch (e) { return 0; }
		});
		if (UrlSpeed > 0.0) S = static_cast<float>(UrlSpeed);
#endif
		Cached = FMath::Clamp(S, 0.25f, 8.f);
	}
	return Cached;
}

// Examples of the debug switches Starseal grew (each is one cached UrlOrCmd). Names are Starseal's; the idea is that
// every "I need to look at X" becomes a switch that jumps straight to X and takes the pictures.
bool NoHud()        { static int C = -1; if (C < 0) C = UrlOrCmd(TEXT("SGNoHud"), "sgnohud") ? 1 : 0; return C == 1; }        // trailer recording: no HUD
bool PatrolCheck()  { static int C = -1; if (C < 0) C = UrlOrCmd(TEXT("SGPatrol"), "sgpatrol") ? 1 : 0; return C == 1; }      // walk every path, a picture every 3.5 m
bool LayoutCheck()  { static int C = -1; if (C < 0) C = UrlOrCmd(TEXT("SGLayout"), "sglayout") ? 1 : 0; return C == 1; }      // every UI card / button with its longest text
bool Trace()        { static int C = -1; if (C < 0) C = UrlOrCmd(TEXT("SGTrace"), "sgtrace") ? 1 : 0; return C == 1; }        // SG_POS twice a second (input tests read yaw / distance)
bool DebugBattle()  { static int C = -1; if (C < 0) C = UrlOrCmd(TEXT("SGBattle"), "sgbattle") ? 1 : 0; return C == 1; }      // start a battle 12 s into exploring
bool StillCam()     { static int C = -1; if (C < 0) C = UrlOrCmd(TEXT("SGStillCam"), "sgstillcam") ? 1 : 0; return C == 1; }  // no camera drift: pixel diffs prove what moves
bool FakeLowFps()   { static int C = -1; if (C < 0) C = UrlOrCmd(TEXT("SGFakeLowFps"), "sgfakelowfps") ? 1 : 0; return C == 1; } // test the dynamic-resolution guard

// Screenshot by name. Native: written to -SGShotDir=<ABSOLUTE dir> (a relative path resolves against the engine
// binary's folder, not yours). Wasm: only the log line; the browser test takes the page screenshot when it sees it.
void Shot(const FString& Name)
{
	Log(FString::Printf(TEXT("SG_SHOT %s"), *Name));
#if !PLATFORM_WASM
	FString Dir;
	if (!FParse::Value(FCommandLine::Get(), TEXT("SGShotDir="), Dir))
	{
		Dir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Screenshots"), TEXT("SG"));
	}
	FScreenshotRequest::RequestScreenshot(FPaths::Combine(Dir, Name + TEXT(".png")), true, false);
#endif
}

// What a run really loads (?sgpkgdump / -SGPkgDump): one SG_PKG line per /Game and /Engine package. Print it BEFORE
// SG_DONE: the test scripts stop reading at SG_DONE. It proves "this run used X", never "nothing uses Y".
// (needs "UObject/Package.h" and "UObject/UObjectIterator.h")
}  // namespace SG
