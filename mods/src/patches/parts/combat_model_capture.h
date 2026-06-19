#pragma once

#include <prime/EntityGroup.h>

#include <cstdint>
#include <string_view>

#include <nlohmann/json_fwd.hpp>

namespace combat_model_capture
{
bool ShouldCaptureEntityGroup(EntityGroup::Type type);
void CaptureEntityGroup(EntityGroup::Type type, std::string_view bytes);
void CaptureBattleJournal(uint64_t journal_id, const nlohmann::json& battle_json);
} // namespace combat_model_capture
