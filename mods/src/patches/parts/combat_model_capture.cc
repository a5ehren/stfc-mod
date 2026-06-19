#include "combat_model_capture.h"

#include "config.h"
#include "file.h"

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <string>
#include <string_view>
#include <unordered_set>

namespace combat_model_capture
{
namespace
{
std::mutex              capture_mtx;
std::atomic_uint64_t    capture_counter{0};
std::unordered_set<int> captured_static_groups;

std::string EntityGroupName(EntityGroup::Type type)
{
  switch (type) {
    case EntityGroup::Type::BattleConfig:
      return "BattleConfig";
    case EntityGroup::Type::ThreatConfig:
      return "ThreatConfig";
    case EntityGroup::Type::ClientShipStatLookupSpecs:
      return "ClientShipStatLookupSpecs";
    case EntityGroup::Type::BaseShipTierSpecs:
      return "BaseShipTierSpecs";
    case EntityGroup::Type::ShipTierSpecs:
      return "ShipTierSpecs";
    case EntityGroup::Type::ShipBonusBuffSpecs:
      return "ShipBonusBuffSpecs";
    case EntityGroup::Type::MitigationCapsSpecs:
      return "MitigationCapsSpecs";
    case EntityGroup::Type::GlobalDamageReductionConfig:
      return "GlobalDamageReductionConfig";
    case EntityGroup::Type::HullSpecs:
      return "HullSpecs";
    case EntityGroup::Type::ComponentSpecs:
      return "ComponentSpecs";
    case EntityGroup::Type::OfficerSpecs:
      return "OfficerSpecs";
    case EntityGroup::Type::Officers:
      return "Officers";
    case EntityGroup::Type::OfficerAbilityBuffSpecs:
      return "OfficerAbilityBuffSpecs";
    case EntityGroup::Type::OfficerCoreStatSpecs:
      return "OfficerCoreStatSpecs";
    case EntityGroup::Type::OfficerCoreStatThresholdsSpecs:
      return "OfficerCoreStatThresholdsSpecs";
    case EntityGroup::Type::OfficerSynergyFactorSpecs:
      return "OfficerSynergyFactorSpecs";
    case EntityGroup::Type::BuffTargetSpecs:
      return "BuffTargetSpecs";
    case EntityGroup::Type::BuffTriggerSpecs:
      return "BuffTriggerSpecs";
    case EntityGroup::Type::ActionSpecs:
      return "ActionSpecs";
    case EntityGroup::Type::ShipLevelUpBonusBuffsSpecs:
      return "ShipLevelUpBonusBuffsSpecs";
    case EntityGroup::Type::ResearchSpecs:
      return "ResearchSpecs";
    case EntityGroup::Type::ResearchTreesState:
      return "ResearchTreesState";
    case EntityGroup::Type::StarbaseBuffs:
      return "StarbaseBuffs";
    case EntityGroup::Type::GlobalActiveBuffs:
      return "GlobalActiveBuffs";
    case EntityGroup::Type::ConsumableSpecs:
      return "ConsumableSpecs";
    case EntityGroup::Type::SlotSpecs:
      return "SlotSpecs";
    case EntityGroup::Type::ConsumableBuffs:
      return "ConsumableBuffs";
    case EntityGroup::Type::EntitySlots:
      return "EntitySlots";
    case EntityGroup::Type::EntitySlotsData:
      return "EntitySlotsData";
    case EntityGroup::Type::ActiveOfficerTraits:
      return "ActiveOfficerTraits";
    case EntityGroup::Type::CommanderSkillSpecs:
      return "CommanderSkillSpecs";
    case EntityGroup::Type::ForbiddenTechSpecs:
      return "ForbiddenTechSpecs";
    case EntityGroup::Type::ForbiddenTechs:
      return "ForbiddenTechs";
    case EntityGroup::Type::ForbiddenTechBuffs:
      return "ForbiddenTechBuffs";
    case EntityGroup::Type::ActivatedAbilitySpecs:
      return "ActivatedAbilitySpecs";
    case EntityGroup::Type::ActivatedShipAbilitiesConfigs:
      return "ActivatedShipAbilitiesConfigs";
    default:
      return {};
  }
}

std::filesystem::path CaptureRoot()
{
  if (!Config::Get().combat_model_capture_dir.empty()) {
    return Config::Get().combat_model_capture_dir;
  }
  return File::MakePath("combat_model_captures", true);
}

std::string NextStem(const std::string& prefix)
{
  const auto now = std::chrono::duration_cast<std::chrono::milliseconds>(
                       std::chrono::system_clock::now().time_since_epoch())
                       .count();
  return prefix + "-" + std::to_string(now) + "-" + std::to_string(capture_counter.fetch_add(1));
}

void AppendManifest(const nlohmann::json& entry)
{
  const auto    manifest_path = CaptureRoot() / "manifest.jsonl";
  std::ofstream manifest(manifest_path, std::ios::app);
  manifest << entry.dump() << '\n';
}

} // namespace

bool ShouldCaptureEntityGroup(EntityGroup::Type type)
{
  return !EntityGroupName(type).empty();
}

void CaptureEntityGroup(EntityGroup::Type type, std::string_view bytes)
{
  if (!Config::Get().combat_model_capture_enabled || !ShouldCaptureEntityGroup(type)) {
    return;
  }

  std::scoped_lock lk(capture_mtx);
  const int         group_code = static_cast<int>(type);
  if (captured_static_groups.contains(group_code)) {
    return;
  }
  captured_static_groups.insert(group_code);

  const auto group_name = EntityGroupName(type);
  const auto root       = CaptureRoot();
  const auto rel_path   = std::filesystem::path("static") / (NextStem(group_name) + ".pb");
  const auto abs_path   = root / rel_path;

  std::error_code ec;
  std::filesystem::create_directories(abs_path.parent_path(), ec);
  if (ec) {
    spdlog::error("combat model capture: failed to create {}: {}", abs_path.parent_path().string(), ec.message());
    return;
  }

  std::ofstream out(abs_path, std::ios::binary);
  out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
  if (!out.good()) {
    spdlog::error("combat model capture: failed to write {}", abs_path.string());
    return;
  }

  AppendManifest({{"kind", "entity_group"},
                  {"entity_group", group_name},
                  {"entity_group_code", group_code},
                  {"path", rel_path.generic_string()},
                  {"bytes", bytes.size()}});
}

void CaptureBattleJournal(uint64_t journal_id, const nlohmann::json& battle_json)
{
  if (!Config::Get().combat_model_capture_enabled) {
    return;
  }

  std::scoped_lock lk(capture_mtx);
  const auto       root     = CaptureRoot();
  const auto       rel_path = std::filesystem::path("battles") / (std::to_string(journal_id) + ".json");
  const auto       abs_path = root / rel_path;

  std::error_code ec;
  std::filesystem::create_directories(abs_path.parent_path(), ec);
  if (ec) {
    spdlog::error("combat model capture: failed to create {}: {}", abs_path.parent_path().string(), ec.message());
    return;
  }

  std::ofstream out(abs_path);
  out << battle_json.dump(2) << '\n';
  if (!out.good()) {
    spdlog::error("combat model capture: failed to write {}", abs_path.string());
    return;
  }

  AppendManifest({{"kind", "battle_journal"}, {"journal_id", journal_id}, {"path", rel_path.generic_string()}});
}
} // namespace combat_model_capture
