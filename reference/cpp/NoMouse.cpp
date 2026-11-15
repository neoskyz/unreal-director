// REFERENCE ONLY: excerpts from Starseal (its game module file and SGGameMode.cpp). Why: an off-screen test run of the game
// kept warping the user's cursor to the middle of the screen while they worked in another app.
//
// Cause: the project's input settings capture the mouse on launch and lock it to the viewport; exploring used
// FInputModeGameOnly (hidden cursor + capture). On macOS a captured hidden cursor is warped back to the window centre
// every frame. -RenderOffscreen only hides the window; input capture still happens.
// Fix in two places, plus scripts/native/mouse_guard.py as the second line of defence.

// ---- 1. Game module startup: before the viewport exists, turn the capture settings off for unattended runs --------
#include "GameFramework/InputSettings.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Modules/ModuleManager.h"

class FMyGameModule : public FDefaultGameModuleImpl
{
public:
	virtual void StartupModule() override
	{
		// (the same test as SG::NoMouse(); the module starts before the rest of the game code can be used)
		const TCHAR* C = FCommandLine::Get();
		const bool bNoMouse = FParse::Param(C, TEXT("SGAutoPlay")) || FParse::Param(C, TEXT("RenderOffscreen")) || FParse::Param(C, TEXT("SGNoMouse")) ||
							  FCString::Stristr(C, TEXT("-SGRecord=")) != nullptr;
		if (bNoMouse)
		{
			if (UInputSettings* S = GetMutableDefault<UInputSettings>())
			{
				S->bCaptureMouseOnLaunch = false;
				S->DefaultViewportMouseCaptureMode = EMouseCaptureMode::NoCapture;
				S->DefaultViewportMouseLockMode = EMouseLockMode::DoNotLock;
			}
		}
	}
};
// IMPLEMENT_PRIMARY_GAME_MODULE(FMyGameModule, MyGame, "MyGame");

// ---- 2. Wherever the game sets its input mode: never GameOnly when unattended --------------------------------------
#include "Framework/Application/SlateApplication.h"
#include "Engine/GameViewportClient.h"
#include "GameFramework/PlayerController.h"

void ApplyInputModeUnattended(APlayerController* P, UWorld* World)
{
	// unattended run: the game drives itself. Never capture, lock, hide or move the system mouse.
	P->SetShowMouseCursor(true);
	FInputModeGameAndUI Mode;
	Mode.SetLockMouseToViewportBehavior(EMouseLockMode::DoNotLock);
	Mode.SetHideCursorDuringCapture(false);
	P->SetInputMode(Mode);
	if (UGameViewportClient* V = World ? World->GetGameViewport() : nullptr)
	{
		V->SetMouseCaptureMode(EMouseCaptureMode::NoCapture);
		V->SetMouseLockMode(EMouseLockMode::DoNotLock);
		V->SetHideCursorDuringCapture(false);
	}
	if (FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().ReleaseAllPointerCapture();
		if (TSharedPtr<GenericApplication> App = FSlateApplication::Get().GetPlatformApplication())
		{
			App->SetCapture(nullptr);
			App->SetHighPrecisionMouseMode(false, nullptr);
		}
	}
}
// In the game mode: if (SG::NoMouse()) ApplyInputModeUnattended(PC, GetWorld()); else { the normal GameOnly path }.
// A hand-played build (no switches) keeps capturing the mouse as usual.
