#include "relocators.h"
#include "asmjit/core/globals.h"
#include "detour/detour_impl.h"

#include <spud/utils.h>

#include <capstone/arm64.h>

#include <cassert>

namespace spud::detail::arm64 {

using namespace asmjit;
using namespace asmjit::a64;

const static relocation_meta generic_relocator = {
    .size = sizeof(uintptr_t),
    .gen_relo_data =
        [](auto target, auto &relo, auto data_label, Assembler &assembler,
           auto &) {
          auto target_start = reinterpret_cast<uintptr_t>(target.data());
          ZyanU64 absolute_target = 0;
          const auto &op = relo.detail.operands[1];
          if (op.type == AARCH64_OP_IMM) {
            const auto offset = op.imm;
            assembler.bind(data_label);
            assembler.embed(&offset, sizeof(offset));
            assembler.embed(&offset, sizeof(offset));
          } else {
            assert(false && "Expected IMM register");
          }
        },
    .gen_relo_code =
        [](std::span<uint8_t>, const relocation_entry &relo,
           const relocation_info &, asmjit::Label relocation_data,
           Assembler &assembler) {
          auto instruction = relo.instruction;

          const auto &detail = relo.detail;
          const auto &op = detail.operands[0];

          GpX target_register;
          switch (op.reg) {
          case ARM64_REG_X0:
            target_register = x0;
            break;
          case ARM64_REG_X1:
            target_register = x1;
            break;
          case ARM64_REG_X2:
            target_register = x2;
            break;
          case ARM64_REG_X3:
            target_register = x3;
            break;
          case ARM64_REG_X4:
            target_register = x4;
            break;
          case ARM64_REG_X5:
            target_register = x5;
            break;
          case ARM64_REG_X6:
            target_register = x6;
            break;
          case ARM64_REG_X7:
            target_register = x7;
            break;
          case ARM64_REG_X8:
            target_register = x8;
            break;
          case ARM64_REG_X9:
            target_register = x9;
            break;
          case ARM64_REG_X10:
            target_register = x10;
            break;
          case ARM64_REG_X11:
            target_register = x11;
            break;
          case ARM64_REG_X12:
            target_register = x12;
            break;
          case ARM64_REG_X13:
            target_register = x13;
            break;
          case ARM64_REG_X14:
            target_register = x14;
            break;
          case ARM64_REG_X15:
            target_register = x15;
            break;
          case ARM64_REG_X16:
            target_register = x16;
            break;
          case ARM64_REG_X17:
            target_register = x17;
            break;
          case ARM64_REG_X18:
            target_register = x18;
            break;
          case ARM64_REG_X19:
            target_register = x19;
            break;
          case ARM64_REG_X20:
            target_register = x20;
            break;
          case ARM64_REG_X21:
            target_register = x21;
            break;
          case ARM64_REG_X22:
            target_register = x22;
            break;
          case ARM64_REG_X23:
            target_register = x23;
            break;
          case ARM64_REG_X24:
            target_register = x24;
            break;
          case ARM64_REG_X25:
            target_register = x25;
            break;
          case ARM64_REG_X26:
            target_register = x26;
            break;
          case ARM64_REG_X27:
            target_register = x27;
            break;
          case ARM64_REG_X28:
            target_register = x28;
            break;
          default:
            assert(false && "unsupported register");
          }
          // assembler.adr(target_register, relocation_data);
          //
          assembler.sub(sp, sp, 16);
          // assembler.str(x20, Mem{sp, 0});
          assembler.ldr(target_register, Mem{relocation_data, 0});
          // assembler.mov(target_register, x20);
          // assembler.ldr(x20, Mem{sp, 0});
          assembler.add(sp, sp, 16);
        }};

const static relocation_meta ldr_literal_relocator = {
    .size = sizeof(uintptr_t),
    .gen_relo_data =
        [](auto target, auto &relo, auto data_label, Assembler &assembler,
           auto &) {
          // The IMM operand contains the absolute address the LDR was targeting
          const auto &op = relo.detail.operands[1];
          uintptr_t source_address = op.imm;

          // Embed the source address so the trampoline can dereference it at
          // runtime. This handles both constant and mutable data correctly.
          assembler.bind(data_label);
          assembler.embed(&source_address, sizeof(source_address));
        },
    .gen_relo_code =
        [](std::span<uint8_t>, const relocation_entry &relo,
           const relocation_info &, asmjit::Label relocation_data,
           Assembler &assembler) {
          const auto &detail = relo.detail;
          const auto &op = detail.operands[0];

          // Determine if this is a W-register (32-bit) or X-register (64-bit)
          // load, or a LDRSW (sign-extending 32-bit to 64-bit)
          bool is_w_reg = op.reg >= ARM64_REG_W0 && op.reg <= ARM64_REG_W28;

          // Map to the corresponding X register for the intermediate load
          GpX target_register;
          if (is_w_reg) {
            // W0-W28 map to X0-X28 (W regs are the low 32 bits of X regs)
            int reg_idx = op.reg - ARM64_REG_W0;
            switch (reg_idx) {
            case 0: target_register = x0; break;
            case 1: target_register = x1; break;
            case 2: target_register = x2; break;
            case 3: target_register = x3; break;
            case 4: target_register = x4; break;
            case 5: target_register = x5; break;
            case 6: target_register = x6; break;
            case 7: target_register = x7; break;
            case 8: target_register = x8; break;
            case 9: target_register = x9; break;
            case 10: target_register = x10; break;
            case 11: target_register = x11; break;
            case 12: target_register = x12; break;
            case 13: target_register = x13; break;
            case 14: target_register = x14; break;
            case 15: target_register = x15; break;
            case 16: target_register = x16; break;
            case 17: target_register = x17; break;
            case 18: target_register = x18; break;
            case 19: target_register = x19; break;
            case 20: target_register = x20; break;
            case 21: target_register = x21; break;
            case 22: target_register = x22; break;
            case 23: target_register = x23; break;
            case 24: target_register = x24; break;
            case 25: target_register = x25; break;
            case 26: target_register = x26; break;
            case 27: target_register = x27; break;
            case 28: target_register = x28; break;
            default:
              assert(false && "unsupported W register for LDR literal relocation");
            }
          } else {
            switch (op.reg) {
            case ARM64_REG_X0: target_register = x0; break;
            case ARM64_REG_X1: target_register = x1; break;
            case ARM64_REG_X2: target_register = x2; break;
            case ARM64_REG_X3: target_register = x3; break;
            case ARM64_REG_X4: target_register = x4; break;
            case ARM64_REG_X5: target_register = x5; break;
            case ARM64_REG_X6: target_register = x6; break;
            case ARM64_REG_X7: target_register = x7; break;
            case ARM64_REG_X8: target_register = x8; break;
            case ARM64_REG_X9: target_register = x9; break;
            case ARM64_REG_X10: target_register = x10; break;
            case ARM64_REG_X11: target_register = x11; break;
            case ARM64_REG_X12: target_register = x12; break;
            case ARM64_REG_X13: target_register = x13; break;
            case ARM64_REG_X14: target_register = x14; break;
            case ARM64_REG_X15: target_register = x15; break;
            case ARM64_REG_X16: target_register = x16; break;
            case ARM64_REG_X17: target_register = x17; break;
            case ARM64_REG_X18: target_register = x18; break;
            case ARM64_REG_X19: target_register = x19; break;
            case ARM64_REG_X20: target_register = x20; break;
            case ARM64_REG_X21: target_register = x21; break;
            case ARM64_REG_X22: target_register = x22; break;
            case ARM64_REG_X23: target_register = x23; break;
            case ARM64_REG_X24: target_register = x24; break;
            case ARM64_REG_X25: target_register = x25; break;
            case ARM64_REG_X26: target_register = x26; break;
            case ARM64_REG_X27: target_register = x27; break;
            case ARM64_REG_X28: target_register = x28; break;
            default:
              assert(false && "unsupported X register for LDR literal relocation");
            }
          }

          // Load the embedded address from the data section
          assembler.ldr(target_register, Mem{relocation_data, 0});
          // Dereference to get the actual value
          if (is_w_reg) {
            // 32-bit load into W register (zero-extends to X)
            GpW w_target;
            int reg_idx = op.reg - ARM64_REG_W0;
            switch (reg_idx) {
            case 0: w_target = w0; break;
            case 1: w_target = w1; break;
            case 2: w_target = w2; break;
            case 3: w_target = w3; break;
            case 4: w_target = w4; break;
            case 5: w_target = w5; break;
            case 6: w_target = w6; break;
            case 7: w_target = w7; break;
            case 8: w_target = w8; break;
            case 9: w_target = w9; break;
            case 10: w_target = w10; break;
            case 11: w_target = w11; break;
            case 12: w_target = w12; break;
            case 13: w_target = w13; break;
            case 14: w_target = w14; break;
            case 15: w_target = w15; break;
            case 16: w_target = w16; break;
            case 17: w_target = w17; break;
            case 18: w_target = w18; break;
            case 19: w_target = w19; break;
            case 20: w_target = w20; break;
            case 21: w_target = w21; break;
            case 22: w_target = w22; break;
            case 23: w_target = w23; break;
            case 24: w_target = w24; break;
            case 25: w_target = w25; break;
            case 26: w_target = w26; break;
            case 27: w_target = w27; break;
            case 28: w_target = w28; break;
            default:
              assert(false && "unsupported W register for LDR literal relocation");
            }
            assembler.ldr(w_target, ptr(target_register));
          } else if (relo.instruction.id == ARM64_INS_LDRSW) {
            // LDRSW: sign-extending 32-bit load into X register
            assembler.ldrsw(target_register, ptr(target_register));
          } else {
            // 64-bit load
            assembler.ldr(target_register, ptr(target_register));
          }
        },
    .copy_instruction = false};

const static relocation_meta branch_relocator = {
    .size = sizeof(uintptr_t),
    .gen_relo_data =
        [](auto target, auto &relo, auto data_label, Assembler &assembler,
           auto &) {
          const auto label_error = assembler.bind(data_label);
          ASMJIT_ASSERT(label_error == kErrorOk);
          SPUD_UNUSED(label_error);
          auto has_group = [&](uint8_t group) {
            for (size_t i = 0; i < relo.instruction.detail->groups_count; i++) {
              if (relo.instruction.detail->groups[i] == group) {
                return true;
              }
            }
            return false;
          };
          const auto &detail = relo.detail;
          intptr_t result = 0;
          if (has_group(ARM64_GRP_BRANCH_RELATIVE) ||
              has_group(ARM64_GRP_JUMP) || has_group(ARM64_GRP_CALL)) {
            result = detail.operands[detail.op_count - 1].imm;
          }
          const auto target_start = reinterpret_cast<intptr_t>(target.data());
          Label L1 = assembler.newLabel();
          assembler.ldr(x16, ptr(L1));
          assembler.br(x16);
          assembler.bind(L1);
          assembler.embed(&result, sizeof(result));
        },
    .gen_relo_code = [](std::span<uint8_t>, const relocation_entry &relo,
                        const relocation_info &, asmjit::Label relocation_data,
                        Assembler &assembler) {},
    .copy_instruction = true};

const relocation_meta &
get_relocator_for_instruction(const cs_insn &instruction) {
  auto has_group = [&](uint8_t group) {
    for (size_t i = 0; i < instruction.detail->groups_count; i++) {
      if (instruction.detail->groups[i] == group) {
        return true;
      }
    }
    return false;
  };
  if (has_group(ARM64_GRP_BRANCH_RELATIVE) || has_group(ARM64_GRP_JUMP) ||
      has_group(ARM64_GRP_CALL)) {
    return branch_relocator;
  }
  // LDR literal (PC-relative load) needs its own relocator
  if (instruction.id == ARM64_INS_LDR || instruction.id == ARM64_INS_LDRSW) {
    const auto &detail = instruction.detail->aarch64;
    if (detail.op_count >= 2 && detail.operands[1].type == AARCH64_OP_IMM) {
      return ldr_literal_relocator;
    }
  }
  return generic_relocator;
}

} // namespace spud::detail::arm64
