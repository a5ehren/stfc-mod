#include "config.h"
#include "errormsg.h"
#include "prime/TransitionManager.h"

#include <il2cpp/il2cpp_helper.h>

#include <spdlog/spdlog.h>
#include <spud/detour.h>

#include "patches/safe_detour.h"

int64_t TransitionManager_Awake(auto original, TransitionManager* a1)
{
  spdlog::debug("Adjusting screen transitions to {}", Config::Get().transition_time);
  auto r                         = original(a1);
  a1->SBlurController->_blurTime = std::clamp(Config::Get().transition_time, 0.02f, 1.0f);
  return r;
}

int64_t TransitionManager_OnEnable(auto original, TransitionManager* a1)
{
  return 0;
}

void InstallImproveResponsivenessHooks()
{
  auto transition_manager_helper =
      il2cpp_get_class_helper("Assembly-CSharp", "Digit.Prime.LoadingScreen", "TransitionManager");
  if (!transition_manager_helper.isValidHelper()) {
    ErrorMsg::MissingHelper("LoadingScreen", "TransitionManager");
  } else {
    SAFE_STATIC_DETOUR(transition_manager_helper, "TransitionManager", "Awake", 0, TransitionManager_Awake);
  }
}
