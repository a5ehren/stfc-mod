target("stfc-community-mod")
do
    set_kind("shared")
    add_files("src/*.cc")
    -- src/self_update.cc is included by src/*.cc; these packages are used by that updater.
    add_files("src/*.rc")
    add_files("src/version.def")
    add_packages("cpr", "nlohmann_json", "toml++")
    add_shflags("/DEF:src/version.def")
    add_deps("mods")
    set_exceptions("cxx")
    if is_plat("windows") then
        add_cxflags("/bigobj")
        add_links("Shell32.lib")
    end
    set_policy("build.optimization.lto", true)
    add_links("User32.lib", "Ole32.lib", "OleAut32.lib")
end
