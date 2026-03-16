#include "config.h"
#include "errormsg.h"

#include "prime/ActionRequirement.h"
#include "prime/BlurController.h"
#include "prime/BookmarksManager.h"
#include "prime/CallbackContainer.h"
#include "prime/ChatManager.h"
#include "prime/ChatMessageListLocalViewController.h"
#include "prime/ClientModifierType.h"
#include "prime/DeploymentManager.h"
#include "prime/FleetLocalViewController.h"
#include "prime/FleetsManager.h"
#include "prime/FullScreenChatViewController.h"
#include "prime/Hub.h"
#include "prime/InventoryForPopup.h"
#include "prime/KeyCode.h"
#include "prime/NavigationSectionManager.h"
#include "prime/ScanTargetViewController.h"
#include "prime/SceneManager.h"
#include "prime/ScreenManager.h"
#include <prime/UIBehaviour.h>

#include <il2cpp/il2cpp_helper.h>
#include <spud/detour.h>
#include <spud/signature.h>

#include "patches/safe_detour.h"

class AppConfig
{
public:
  __declspec(property(get = __get_PlatformSettingsUrl, put = __set_PlatformSettingsUrl))
  Il2CppString*                                                                                  PlatformSettingsUrl;
  __declspec(property(get = __get_PlatformApiKey, put = __set_PlatformApiKey)) Il2CppString*     PlatformApiKey;
  __declspec(property(get = __get_AssetUrlOverride, put = __set_AssetUrlOverride)) Il2CppString* AssetUrlOverride;

private:
  static IL2CppClassHelper& get_class_helper()
  {
    static auto class_helper = il2cpp_get_class_helper("Assembly-CSharp", "Digit.Client.Core", "AppConfig");
    return class_helper;
  }

public:
  Il2CppString* __get_PlatformSettingsUrl()
  {
    static auto prop = get_class_helper().GetProperty("PlatformSettingsUrl");
    return prop.GetRaw<Il2CppString>((void*)this);
  }

  void __set_PlatformSettingsUrl(Il2CppString* v)
  {
    static auto prop = get_class_helper().GetProperty("PlatformSettingsUrl");
    return prop.SetRaw((void*)this, *v);
  }

  Il2CppString* __get_PlatformApiKey()
  {
    static auto prop = get_class_helper().GetProperty("PlatformApiKey");
    return prop.GetRaw<Il2CppString>((void*)this);
  }

  void __set_PlatformApiKey(Il2CppString* v)
  {
    static auto prop = get_class_helper().GetProperty("PlatformApiKey");
    return prop.SetRaw((void*)this, *v);
  }

  Il2CppString* __get_AssetUrlOverride()
  {
    static auto prop = get_class_helper().GetProperty("AssetUrlOverride");
    return prop.GetRaw<Il2CppString>((void*)this);
  }

  void __set_AssetUrlOverride(Il2CppString* v)
  {
    static auto prop = get_class_helper().GetProperty("AssetUrlOverride");
    return prop.SetRaw((void*)this, *v);
  }
};

class Model
{
public:
  __declspec(property(get = __get_AppConfig)) AppConfig* AppConfig_;

private:
  static IL2CppClassHelper& get_class_helper()
  {
    static auto class_helper = il2cpp_get_class_helper("Assembly-CSharp", "Digit.Client.Core", "Model");
    return class_helper;
  }

public:
  AppConfig* __get_AppConfig()
  {
    static auto field = get_class_helper().GetField("_appConfig");
    return *(AppConfig**)((ptrdiff_t)this + field.offset());
  }
};

void Cursor_SetCursor(auto original, void* _this, ptrdiff_t texture, Vector2* hotspot, int cursorMode)
{
#if _WIN32
  if (!Config::Get().allow_cursor) {
    SetCursor(LoadCursor(NULL, IDC_ARROW));
    ClipCursor(nullptr); // free cursor from any Unity clipping
    return;
  }
#endif

  return original(_this, texture, hotspot, cursorMode);
}

AppConfig* Model_LoadConfigs(auto original, Model* _this)
{
  original(_this);
  auto config = _this->AppConfig_;

  if (!Config::Get().config_settings_url.empty()) {
    auto new_settings_url       = il2cpp_string_new(Config::Get().config_settings_url.c_str());
    config->PlatformSettingsUrl = new_settings_url;
  }

  if (!Config::Get().config_assets_url_override.empty()) {
    auto new_url             = il2cpp_string_new(Config::Get().config_assets_url_override.c_str());
    config->AssetUrlOverride = new_url;
  }

  return config;
}


bool IsQueueEnabled(auto original, void* _this)
{
  if (Config::Get().queue_enabled) {
    return original(_this);
  }

  return false;
}

void InstallTestPatches()
{
  auto cursorManager = il2cpp_get_class_helper("UnityEngine.CoreModule", "UnityEngine", "Cursor");
  if (!cursorManager.isValidHelper()) {
    ErrorMsg::MissingHelper("UnityEngine", "Cursor");
  } else {
    SAFE_STATIC_DETOUR(cursorManager, "Cursor", "SetCursor_Injected", 3, Cursor_SetCursor);
  }

  auto model = il2cpp_get_class_helper("Assembly-CSharp", "Digit.Client.Core", "Model");
  if (!model.isValidHelper()) {
    ErrorMsg::MissingHelper("Core", "Model");
  } else {
    SAFE_STATIC_DETOUR(model, "Model", "LoadConfigs", 0, Model_LoadConfigs);
  }

  auto queue_manager = il2cpp_get_class_helper("Assembly-CSharp", "Prime.ActionQueue", "ActionQueueManager");
  if (!queue_manager.isValidHelper()) {
    ErrorMsg::MissingHelper("ActionQueue", "ActionQueueManager");
  } else {
    SAFE_STATIC_DETOUR(queue_manager, "ActionQueueManager", "IsQueueUnlocked", 0, IsQueueEnabled);
  }
}
