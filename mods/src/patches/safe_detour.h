#pragma once

#include <il2cpp/il2cpp_helper.h>

#include <spdlog/spdlog.h>
#include <spud/detour.h>

#include <unordered_set>

namespace SafeDetour
{

inline void LogMethodParams(const MethodInfo* method_info, const char* class_name, const char* method_name)
{
  for (uint32_t i = 0; i < method_info->parameters_count; ++i) {
    auto param_type = il2cpp_method_get_param(method_info, i);
    auto param_name = il2cpp_method_get_param_name(method_info, i);
    auto type_name  = il2cpp_type_get_name(param_type);
    spdlog::info("  {}::{} param[{}]: {} {}", class_name, method_name, i, type_name ? type_name : "???",
                 param_name ? param_name : "???");
    if (type_name) il2cpp_free(type_name);
  }
}

// Dump all methods on a class for diagnosis when a method lookup fails.
inline void DumpClassMethods(IL2CppClassHelper& helper, const char* class_name)
{
  auto* cls = helper.get_cls();
  if (!cls) {
    spdlog::warn("  [dump] {} — class is null, cannot enumerate methods", class_name);
    return;
  }

  spdlog::info("  [dump] All methods on '{}':", class_name);
  void*             iter   = nullptr;
  const MethodInfo* method = nullptr;
  int               count  = 0;
  while ((method = il2cpp_class_get_methods(cls, &iter)) != nullptr) {
    spdlog::info("    {}({} params)", method->name ? method->name : "???", method->parameters_count);
    for (uint32_t i = 0; i < method->parameters_count; ++i) {
      auto param_type = il2cpp_method_get_param(method, i);
      auto param_name = il2cpp_method_get_param_name(method, i);
      auto type_name  = il2cpp_type_get_name(param_type);
      spdlog::info("      param[{}]: {} {}", i, type_name ? type_name : "???", param_name ? param_name : "???");
      if (type_name) il2cpp_free(type_name);
    }
    ++count;
  }
  spdlog::info("  [dump] Total: {} methods on {}", count, class_name);
}

// Dump all fields on a class for diagnosis.
inline void DumpClassFields(IL2CppClassHelper& helper, const char* class_name)
{
  auto* cls = helper.get_cls();
  if (!cls) {
    spdlog::warn("  [dump] {} — class is null, cannot enumerate fields", class_name);
    return;
  }

  spdlog::info("  [dump] All fields on '{}':", class_name);
  void*      iter  = nullptr;
  FieldInfo* field = nullptr;
  int        count = 0;
  while ((field = il2cpp_class_get_fields(cls, &iter)) != nullptr) {
    auto type_name = il2cpp_type_get_name(il2cpp_field_get_type(field));
    spdlog::info("    {} {} (offset {})", type_name ? type_name : "???", field->name ? field->name : "???",
                 il2cpp_field_get_offset(field));
    if (type_name) il2cpp_free(type_name);
    ++count;
  }
  spdlog::info("  [dump] Total: {} fields on {}", count, class_name);
}

// Track already-hooked addresses to prevent double-hooking.
// When two IL2CPP classes share the same compiled method, hooking
// the same methodPointer twice corrupts the second trampoline.
inline std::unordered_set<void*>& HookedAddresses()
{
  static std::unordered_set<void*> addresses;
  return addresses;
}

}; // namespace SafeDetour

// Safe detour macro that validates parameter count before installing the hook.
// Logs actual parameter types on mismatch for diagnosis.
// Usage: SAFE_STATIC_DETOUR(class_helper, "ClassName", "MethodName", expected_param_count, hook_function)
#define SAFE_STATIC_DETOUR(helper, class_name, method_name, expected_params, hook_fn)                                  \
  do {                                                                                                                 \
    auto* _sd_method_info = (helper).GetMethodInfo(method_name);                                                       \
    if (_sd_method_info == nullptr) {                                                                                   \
      ErrorMsg::MissingMethod(class_name, method_name);                                                                \
      SafeDetour::DumpClassMethods(helper, class_name);                                                                \
    } else if (static_cast<int>(_sd_method_info->parameters_count) != (expected_params)) {                             \
      spdlog::error("{}::{}: expected {} params, got {} — skipping hook", class_name, method_name, expected_params,    \
                     _sd_method_info->parameters_count);                                                               \
      SafeDetour::LogMethodParams(_sd_method_info, class_name, method_name);                                           \
    } else if (SafeDetour::HookedAddresses().count((void*)_sd_method_info->methodPointer)) {                            \
      spdlog::warn("{}::{}: addr {:#x} already hooked — skipping double-hook", class_name,                             \
                    method_name, reinterpret_cast<uintptr_t>(_sd_method_info->methodPointer));                         \
    } else {                                                                                                           \
      SPUD_STATIC_DETOUR((void*)_sd_method_info->methodPointer, hook_fn);                                              \
      SafeDetour::HookedAddresses().insert((void*)_sd_method_info->methodPointer);                                     \
    }                                                                                                                  \
  } while (0)
