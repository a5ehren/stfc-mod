#include "config.h"
#include "errormsg.h"

#include <il2cpp/il2cpp_helper.h>
#include <prime/Toast.h>

#include <spud/detour.h>

#include "patches/safe_detour.h"

struct ToastObserver {
};

void ToastObserver_EnqueueToast_Hook(auto original, ToastObserver *_this, Toast *toast)
{
  if (std::ranges::find(Config::Get().disabled_banner_types, toast->get_State())
      != Config::Get().disabled_banner_types.end()) {
    return;
  }

  original(_this, toast);
}

void ToastObserver_EnqueueOrCombineToast_Hook(auto original, ToastObserver *_this, Toast *toast, uintptr_t cmpAction)
{
  if (std::ranges::find(Config::Get().disabled_banner_types, toast->get_State())
      != Config::Get().disabled_banner_types.end()) {
    return;
  }

  original(_this, toast, cmpAction);
}

void InstallToastBannerHooks()
{
  if (auto helper = il2cpp_get_class_helper("Assembly-CSharp", "Digit.Prime.HUD", "ToastObserver");
      !helper.isValidHelper()) {
    ErrorMsg::MissingHelper("HUD", "ToastObserver");
  } else {
    SAFE_STATIC_DETOUR(helper, "ToastObserver", "EnqueueToast", 1, ToastObserver_EnqueueToast_Hook);
    SAFE_STATIC_DETOUR(helper, "ToastObserver", "EnqueueOrCombineToast", 2, ToastObserver_EnqueueOrCombineToast_Hook);
  }
}
