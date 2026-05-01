#!/bin/bash

# STFC Community Mod - Code Signing Diagnostic & Backup Script
# Helps identify which files need to be backed up/restored to avoid
# requiring a full game reinstall after mod signing.

set -euo pipefail
# Allow diff to return 1 (files differ) without exiting
diff_files() { diff --color=always "$@" || true; }

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[OK]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
print_header()  { echo -e "\n${CYAN}═══ $1 ═══${NC}\n"; }

BACKUP_BASE="${HOME}/.stfc-signing-debug"

# --- Game path resolution (mirrors launcher logic) ---

find_game_path() {
    local ini_path="${HOME}/Library/Preferences/Star Trek Fleet Command/launcher_settings.ini"
    if [[ ! -f "$ini_path" ]]; then
        print_error "launcher_settings.ini not found at: $ini_path"
        print_info "Is the game installed?"
        exit 1
    fi

    local game_dir
    game_dir=$(grep '152033..GAME_PATH' "$ini_path" | cut -d'=' -f2- | xargs)
    if [[ -z "$game_dir" ]]; then
        print_error "Could not read GAME_PATH from launcher_settings.ini"
        exit 1
    fi

    GAME_APP="${game_dir}/Star Trek Fleet Command.app"
    GAME_EXE="${GAME_APP}/Contents/MacOS/Star Trek Fleet Command"
    GAME_CODESIG_DIR="${GAME_APP}/Contents/_CodeSignature"
    GAME_CODESIG_RESOURCES="${GAME_CODESIG_DIR}/CodeResources"

    if [[ ! -d "$GAME_APP" ]]; then
        print_error "Game app bundle not found at: $GAME_APP"
        exit 1
    fi
    if [[ ! -f "$GAME_EXE" ]]; then
        print_error "Game executable not found at: $GAME_EXE"
        exit 1
    fi
}

# --- Snapshot: capture everything about the current signing state ---

snapshot() {
    local label="${1:-snapshot}"
    local snap_dir="${BACKUP_BASE}/${label}_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$snap_dir"

    print_header "Snapshot: ${label}"
    print_info "Output directory: $snap_dir"

    # 1. Basic file metadata for the executable
    print_info "Recording executable metadata..."
    ls -la "$GAME_EXE" > "${snap_dir}/exe_metadata.txt"
    stat -f "%N  size=%z  modified=%Sm  inode=%i  mode=%Sp" "$GAME_EXE" >> "${snap_dir}/exe_metadata.txt"
    shasum -a 256 "$GAME_EXE" > "${snap_dir}/exe_sha256.txt"
    echo
    cat "${snap_dir}/exe_metadata.txt"
    echo "SHA-256: $(cat "${snap_dir}/exe_sha256.txt" | cut -d' ' -f1)"

    # 2. Code signature details
    print_info "Recording code signature..."
    echo "--- codesign -dvvv ---" > "${snap_dir}/codesign_verbose.txt"
    codesign -dvvv "$GAME_EXE" >> "${snap_dir}/codesign_verbose.txt" 2>&1 || true
    echo >> "${snap_dir}/codesign_verbose.txt"
    echo "--- codesign -dvvv (app bundle) ---" >> "${snap_dir}/codesign_verbose.txt"
    codesign -dvvv "$GAME_APP" >> "${snap_dir}/codesign_verbose.txt" 2>&1 || true
    echo
    cat "${snap_dir}/codesign_verbose.txt"

    # 3. Entitlements
    print_info "Recording entitlements..."
    echo "--- Entitlements (executable) ---" > "${snap_dir}/entitlements.txt"
    codesign -d --entitlements :- "$GAME_EXE" >> "${snap_dir}/entitlements.txt" 2>&1 || echo "(none)" >> "${snap_dir}/entitlements.txt"
    echo >> "${snap_dir}/entitlements.txt"
    echo "--- Entitlements (app bundle) ---" >> "${snap_dir}/entitlements.txt"
    codesign -d --entitlements :- "$GAME_APP" >> "${snap_dir}/entitlements.txt" 2>&1 || echo "(none)" >> "${snap_dir}/entitlements.txt"
    echo
    cat "${snap_dir}/entitlements.txt"

    # 4. Signature verification
    print_info "Verifying signature..."
    echo "--- codesign --verify --deep --strict ---" > "${snap_dir}/verify.txt"
    codesign --verify --deep --strict "$GAME_APP" >> "${snap_dir}/verify.txt" 2>&1 || true
    echo >> "${snap_dir}/verify.txt"
    echo "--- spctl --assess ---" >> "${snap_dir}/verify.txt"
    spctl --assess --type execute "$GAME_APP" >> "${snap_dir}/verify.txt" 2>&1 || true
    echo
    cat "${snap_dir}/verify.txt"

    # 5. _CodeSignature directory
    print_info "Recording _CodeSignature contents..."
    if [[ -d "$GAME_CODESIG_DIR" ]]; then
        ls -laR "$GAME_CODESIG_DIR" > "${snap_dir}/codesig_dir_listing.txt"
        if [[ -f "$GAME_CODESIG_RESOURCES" ]]; then
            shasum -a 256 "$GAME_CODESIG_RESOURCES" > "${snap_dir}/codesig_resources_sha256.txt"
        fi
        cat "${snap_dir}/codesig_dir_listing.txt"
    else
        echo "(no _CodeSignature directory)" > "${snap_dir}/codesig_dir_listing.txt"
        print_warning "No _CodeSignature directory found"
    fi

    # 6. Extended attributes
    print_info "Recording extended attributes..."
    echo "--- xattr (executable) ---" > "${snap_dir}/xattrs.txt"
    xattr -l "$GAME_EXE" >> "${snap_dir}/xattrs.txt" 2>&1 || echo "(none)" >> "${snap_dir}/xattrs.txt"
    echo >> "${snap_dir}/xattrs.txt"
    echo "--- xattr (app bundle) ---" >> "${snap_dir}/xattrs.txt"
    xattr -l "$GAME_APP" >> "${snap_dir}/xattrs.txt" 2>&1 || echo "(none)" >> "${snap_dir}/xattrs.txt"
    echo
    cat "${snap_dir}/xattrs.txt"

    # 7. Check for provisioning profile and receipt
    print_info "Checking for provisioning profiles and receipts..."
    local extras="${snap_dir}/extras.txt"
    : > "$extras"
    for candidate in \
        "${GAME_APP}/Contents/embedded.provisionprofile" \
        "${GAME_APP}/Contents/_MASReceipt/receipt" \
        "${GAME_APP}/Contents/Resources/receipt" \
        ; do
        if [[ -f "$candidate" ]]; then
            echo "FOUND: $candidate ($(stat -f '%z bytes' "$candidate"))" >> "$extras"
            shasum -a 256 "$candidate" >> "$extras"
        else
            echo "NOT FOUND: $candidate" >> "$extras"
        fi
    done
    cat "$extras"

    # 8. Mach-O signature info from the binary
    print_info "Recording Mach-O signature details..."
    echo "--- codesign -d --requirements - ---" > "${snap_dir}/requirements.txt"
    codesign -d --requirements - "$GAME_EXE" >> "${snap_dir}/requirements.txt" 2>&1 || true
    cat "${snap_dir}/requirements.txt"

    # 9. List all nested code (frameworks, plugins)
    print_info "Listing nested signed code..."
    echo "--- Frameworks ---" > "${snap_dir}/nested_code.txt"
    if [[ -d "${GAME_APP}/Contents/Frameworks" ]]; then
        for fw in "${GAME_APP}/Contents/Frameworks"/*; do
            echo "  $fw" >> "${snap_dir}/nested_code.txt"
            codesign -dvv "$fw" >> "${snap_dir}/nested_code.txt" 2>&1 || true
            echo >> "${snap_dir}/nested_code.txt"
        done
    fi
    echo "--- Plugins ---" >> "${snap_dir}/nested_code.txt"
    if [[ -d "${GAME_APP}/Contents/Plugins" ]]; then
        for plug in "${GAME_APP}/Contents/Plugins"/*; do
            echo "  $plug" >> "${snap_dir}/nested_code.txt"
            codesign -dvv "$plug" >> "${snap_dir}/nested_code.txt" 2>&1 || true
            echo >> "${snap_dir}/nested_code.txt"
        done
    fi

    # 10. Full file listing with sizes and hashes for Contents/ (top-level + key dirs)
    print_info "Recording full bundle file inventory..."
    find "$GAME_APP/Contents" -maxdepth 1 -type f -exec shasum -a 256 {} \; > "${snap_dir}/bundle_hashes.txt" 2>/dev/null || true
    find "$GAME_APP/Contents/MacOS" -type f -exec shasum -a 256 {} \; >> "${snap_dir}/bundle_hashes.txt" 2>/dev/null || true
    find "$GAME_CODESIG_DIR" -type f -exec shasum -a 256 {} \; >> "${snap_dir}/bundle_hashes.txt" 2>/dev/null || true
    find "$GAME_APP/Contents" -name "Info.plist" -exec shasum -a 256 {} \; >> "${snap_dir}/bundle_hashes.txt" 2>/dev/null || true

    print_success "Snapshot saved to: $snap_dir"
    echo "$snap_dir"
}

# --- Backup: copy files that might need restoring ---

backup() {
    local backup_dir="${BACKUP_BASE}/backup_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$backup_dir"

    print_header "Backing up signing-critical files"
    print_info "Backup directory: $backup_dir"

    # Back up the executable
    print_info "Backing up game executable..."
    cp "$GAME_EXE" "${backup_dir}/Star Trek Fleet Command"
    shasum -a 256 "${backup_dir}/Star Trek Fleet Command" > "${backup_dir}/Star Trek Fleet Command.sha256"
    print_success "Executable backed up ($(stat -f '%z bytes' "$GAME_EXE"))"

    # Back up _CodeSignature directory
    if [[ -d "$GAME_CODESIG_DIR" ]]; then
        print_info "Backing up _CodeSignature/..."
        cp -R "$GAME_CODESIG_DIR" "${backup_dir}/_CodeSignature"
        print_success "_CodeSignature backed up"
    else
        print_warning "No _CodeSignature directory to back up"
    fi

    # Back up Info.plist
    local info_plist="${GAME_APP}/Contents/Info.plist"
    if [[ -f "$info_plist" ]]; then
        print_info "Backing up Info.plist..."
        cp "$info_plist" "${backup_dir}/Info.plist"
        print_success "Info.plist backed up"
    fi

    # Back up embedded.provisionprofile if it exists
    local prov="${GAME_APP}/Contents/embedded.provisionprofile"
    if [[ -f "$prov" ]]; then
        print_info "Backing up embedded.provisionprofile..."
        cp "$prov" "${backup_dir}/embedded.provisionprofile"
        print_success "Provisioning profile backed up"
    fi

    # Back up any receipt files
    for receipt_path in \
        "${GAME_APP}/Contents/_MASReceipt/receipt" \
        "${GAME_APP}/Contents/Resources/receipt" \
        ; do
        if [[ -f "$receipt_path" ]]; then
            local receipt_name
            receipt_name=$(echo "$receipt_path" | sed "s|${GAME_APP}/Contents/||" | tr '/' '_')
            print_info "Backing up receipt: $receipt_path"
            cp "$receipt_path" "${backup_dir}/${receipt_name}"
            print_success "Receipt backed up as ${receipt_name}"
        fi
    done

    # Back up extended attributes on the executable
    print_info "Backing up extended attributes..."
    xattr -l "$GAME_EXE" > "${backup_dir}/xattrs_exe.txt" 2>&1 || true
    xattr -l "$GAME_APP" > "${backup_dir}/xattrs_app.txt" 2>&1 || true

    # Save metadata about what was backed up
    cat > "${backup_dir}/MANIFEST.txt" << EOF
STFC Signing Debug Backup
Date: $(date)
Game App: ${GAME_APP}
Game Exe: ${GAME_EXE}

Files backed up:
$(ls -la "${backup_dir}/" | tail -n +4)

Original executable SHA-256:
$(shasum -a 256 "$GAME_EXE")

Original codesign info:
$(codesign -dvvv "$GAME_EXE" 2>&1 || true)
EOF

    print_success "Backup complete: $backup_dir"
    echo
    print_info "Use 'restore' to restore individual files from this backup"
}

# --- Restore: restore individual files to test which one matters ---

restore() {
    print_header "Restore from backup"

    # Find the most recent backup
    local latest
    latest=$(ls -dt "${BACKUP_BASE}"/backup_* 2>/dev/null | head -1)
    if [[ -z "$latest" ]]; then
        print_error "No backups found in $BACKUP_BASE"
        exit 1
    fi

    print_info "Latest backup: $latest"
    echo

    # List available files
    echo "Available files to restore:"
    echo
    local i=0
    local files=()
    while IFS= read -r f; do
        [[ "$f" == *MANIFEST.txt ]] && continue
        [[ "$f" == *.sha256 ]] && continue
        [[ "$f" == *xattrs_*.txt ]] && continue
        local basename
        basename=$(basename "$f")
        files+=("$f")
        echo "  [$i] $basename"
        i=$((i + 1))
    done < <(find "$latest" -maxdepth 2 -type f | sort)

    echo
    echo "  [a] ALL files (full restore)"
    echo "  [e] Executable only"
    echo "  [s] _CodeSignature only"
    echo "  [q] Quit"
    echo

    read -p "What to restore? " choice

    case "$choice" in
        q) exit 0 ;;
        a) restore_all "$latest" ;;
        e) restore_executable "$latest" ;;
        s) restore_codesig "$latest" ;;
        [0-9]*)
            if [[ $choice -lt ${#files[@]} ]]; then
                restore_single_file "${files[$choice]}" "$latest"
            else
                print_error "Invalid selection"
                exit 1
            fi
            ;;
        *)
            print_error "Invalid selection"
            exit 1
            ;;
    esac
}

restore_executable() {
    local backup_dir="$1"
    local src="${backup_dir}/Star Trek Fleet Command"
    if [[ ! -f "$src" ]]; then
        print_error "Executable not found in backup"
        return 1
    fi

    print_info "Restoring executable..."
    print_warning "This will overwrite: $GAME_EXE"
    read -p "Continue? [y/N] " -n 1 -r
    echo
    [[ $REPLY =~ ^[Yy]$ ]] || return 0

    cp "$src" "$GAME_EXE"
    print_success "Executable restored"

    # Restore xattrs if we have them
    if [[ -f "${backup_dir}/xattrs_exe.txt" ]]; then
        print_info "(xattr backup exists at ${backup_dir}/xattrs_exe.txt — manual restore if needed)"
    fi
}

restore_codesig() {
    local backup_dir="$1"
    local src="${backup_dir}/_CodeSignature"
    if [[ ! -d "$src" ]]; then
        print_error "_CodeSignature not found in backup"
        return 1
    fi

    print_info "Restoring _CodeSignature/..."
    print_warning "This will overwrite: $GAME_CODESIG_DIR"
    read -p "Continue? [y/N] " -n 1 -r
    echo
    [[ $REPLY =~ ^[Yy]$ ]] || return 0

    rm -rf "$GAME_CODESIG_DIR"
    cp -R "$src" "$GAME_CODESIG_DIR"
    print_success "_CodeSignature restored"
}

restore_all() {
    local backup_dir="$1"
    print_warning "Full restore — will overwrite executable, _CodeSignature, and other files"
    read -p "Continue? [y/N] " -n 1 -r
    echo
    [[ $REPLY =~ ^[Yy]$ ]] || return 0

    restore_executable "$backup_dir" <<< "y"
    restore_codesig "$backup_dir" <<< "y"

    # Restore Info.plist if backed up
    if [[ -f "${backup_dir}/Info.plist" ]]; then
        cp "${backup_dir}/Info.plist" "${GAME_APP}/Contents/Info.plist"
        print_success "Info.plist restored"
    fi

    # Restore provisioning profile if backed up
    if [[ -f "${backup_dir}/embedded.provisionprofile" ]]; then
        cp "${backup_dir}/embedded.provisionprofile" "${GAME_APP}/Contents/embedded.provisionprofile"
        print_success "Provisioning profile restored"
    fi

    print_success "Full restore complete"
}

restore_single_file() {
    local file="$1"
    local backup_dir="$2"
    local basename
    basename=$(basename "$file")

    # Determine destination
    local dest
    case "$basename" in
        "Star Trek Fleet Command") dest="$GAME_EXE" ;;
        "Info.plist") dest="${GAME_APP}/Contents/Info.plist" ;;
        "embedded.provisionprofile") dest="${GAME_APP}/Contents/embedded.provisionprofile" ;;
        "CodeResources") dest="$GAME_CODESIG_RESOURCES" ;;
        *) print_error "Don't know where to restore: $basename"; return 1 ;;
    esac

    print_info "Restoring $basename -> $dest"
    read -p "Continue? [y/N] " -n 1 -r
    echo
    [[ $REPLY =~ ^[Yy]$ ]] || return 0

    cp "$file" "$dest"
    print_success "$basename restored"
}

# --- Diff: compare two snapshots ---

diff_snapshots() {
    print_header "Compare snapshots"

    # Find snapshot dirs (any dir with exe_sha256.txt inside, excluding backups)
    local snaps
    snaps=$(find "${BACKUP_BASE}" -maxdepth 2 -name "exe_sha256.txt" -exec dirname {} \; 2>/dev/null | sort)
    if [[ -z "$snaps" ]]; then
        print_error "No snapshots found. Run 'snapshot' first."
        exit 1
    fi

    local snap_count
    snap_count=$(echo "$snaps" | wc -l | tr -d ' ')
    if [[ "$snap_count" -lt 2 ]]; then
        print_error "Need at least 2 snapshots to diff. Found: $snap_count"
        exit 1
    fi

    local snap_a snap_b
    snap_a=$(echo "$snaps" | head -1)  # first alphabetically (before_*)
    snap_b=$(echo "$snaps" | tail -1)  # last alphabetically (after_*)

    print_info "Comparing:"
    print_info "  BEFORE: $(basename "$snap_a")"
    print_info "  AFTER:  $(basename "$snap_b")"
    echo

    # Compare executable hash
    print_info "Executable SHA-256:"
    local hash_a hash_b
    hash_a=$(cat "${snap_a}/exe_sha256.txt" 2>/dev/null | cut -d' ' -f1)
    hash_b=$(cat "${snap_b}/exe_sha256.txt" 2>/dev/null | cut -d' ' -f1)
    if [[ "$hash_a" == "$hash_b" ]]; then
        print_success "  UNCHANGED"
    else
        print_warning "  BEFORE: ${hash_a}"
        print_warning "  AFTER:  ${hash_b}"
    fi
    echo

    # Compare codesign info
    print_info "Code signature diff:"
    diff_files "${snap_a}/codesign_verbose.txt" "${snap_b}/codesign_verbose.txt"
    echo

    # Compare entitlements
    print_info "Entitlements diff:"
    diff_files "${snap_a}/entitlements.txt" "${snap_b}/entitlements.txt"
    echo

    # Compare verification results
    print_info "Verification diff:"
    diff_files "${snap_a}/verify.txt" "${snap_b}/verify.txt"
    echo

    # Compare _CodeSignature
    print_info "_CodeSignature diff:"
    diff_files "${snap_a}/codesig_dir_listing.txt" "${snap_b}/codesig_dir_listing.txt"
    echo

    # Compare xattrs
    print_info "Extended attributes diff:"
    diff_files "${snap_a}/xattrs.txt" "${snap_b}/xattrs.txt"
    echo

    # Compare bundle hashes
    print_info "Bundle file hashes diff:"
    diff_files "${snap_a}/bundle_hashes.txt" "${snap_b}/bundle_hashes.txt"
    echo

    # Compare requirements
    print_info "Code signing requirements diff:"
    diff_files "${snap_a}/requirements.txt" "${snap_b}/requirements.txt"
}

# --- Status: quick check of current signing state ---

status() {
    print_header "Current signing status"

    print_info "Game executable: $GAME_EXE"
    echo

    print_info "Code signature:"
    codesign -dvvv "$GAME_EXE" 2>&1 || true
    echo

    print_info "Entitlements:"
    codesign -d --entitlements :- "$GAME_EXE" 2>&1 || echo "(none)"
    echo

    print_info "Verification:"
    codesign --verify --deep --strict "$GAME_APP" 2>&1 || true
    echo

    print_info "Gatekeeper assessment:"
    spctl --assess --type execute "$GAME_APP" 2>&1 || true
}

# --- Usage ---

print_usage() {
    cat << 'EOF'
Usage: debug-signing.sh <command>

Commands:
    snapshot [label]   Capture full signing state (run BEFORE and AFTER mod signing)
    backup             Back up all signing-critical files from the game bundle
    restore            Interactively restore backed-up files
    diff               Compare oldest and newest snapshots
    status             Show current signing state
    help               Show this help

Workflow:
    1. Install the game fresh (or repair via official launcher)
    2. Run: debug-signing.sh snapshot before
    3. Run: debug-signing.sh backup
    4. Apply the mod (launch via STFC Community Mod launcher)
    5. Run: debug-signing.sh snapshot after
    6. Run: debug-signing.sh diff
    7. See exactly what changed, then test restoring individual files:
       a. Run: debug-signing.sh restore
       b. Pick "e" (executable only) — try launching the game normally
       c. If that doesn't fix it, restore the mod signing and try "s" (_CodeSignature only)
       d. Try "a" (all) if individual restores don't help

The goal is to identify the minimum set of files to back up before
mod signing so users don't need to reinstall the game to undo it.
EOF
}

# --- Main ---

main() {
    find_game_path

    local cmd="${1:-help}"
    shift 2>/dev/null || true

    case "$cmd" in
        snapshot) snapshot "${1:-snapshot}" ;;
        backup)   backup ;;
        restore)  restore ;;
        diff)     diff_snapshots ;;
        status)   status ;;
        help|-h|--help) print_usage ;;
        *)
            print_error "Unknown command: $cmd"
            print_usage
            exit 1
            ;;
    esac
}

main "$@"
