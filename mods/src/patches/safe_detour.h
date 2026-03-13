#pragma once

#include <il2cpp/il2cpp_helper.h>

#include <spdlog/spdlog.h>
#include <spud/detour.h>

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

}; // namespace SafeDetour

// Safe detour macro that validates parameter count before installing the hook.
// Logs actual parameter types on mismatch for diagnosis.
// Usage: SAFE_STATIC_DETOUR(class_helper, "ClassName", "MethodName", expected_param_count, hook_function)
#define SAFE_STATIC_DETOUR(helper, class_name, method_name, expected_params, hook_fn)                                  \
  do {                                                                                                                 \
    auto* _sd_method_info = (helper).GetMethodInfo(method_name);                                                       \
    if (_sd_method_info == nullptr) {                                                                                   \
      ErrorMsg::MissingMethod(class_name, method_name);                                                                \
    } else if (static_cast<int>(_sd_method_info->parameters_count) != (expected_params)) {                             \
      spdlog::error("{}::{}: expected {} params, got {} — skipping hook", class_name, method_name, expected_params,    \
                     _sd_method_info->parameters_count);                                                               \
      SafeDetour::LogMethodParams(_sd_method_info, class_name, method_name);                                           \
    } else {                                                                                                           \
      SPUD_STATIC_DETOUR((void*)_sd_method_info->methodPointer, hook_fn);                                              \
    }                                                                                                                  \
  } while (0)
