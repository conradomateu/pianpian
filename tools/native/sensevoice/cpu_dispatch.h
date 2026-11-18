#pragma once
// One portable launcher plus an optional static AVX2 sibling: no CPU DLLs or GPU runtime.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <optional>
#include <stdexcept>
#include <string>
#ifdef _WIN32
#include <windows.h>
#include <intrin.h>
#include <immintrin.h>
#endif

namespace pianpian {
struct CpuFeatures {
    uint32_t leaf1_ecx = 0, leaf7_ebx = 0;
    uint64_t xcr0 = 0;
};
inline bool supports_avx2(const CpuFeatures &f) {
    // SSE4.2, FMA, XSAVE, OSXSAVE, AVX, F16C; BMI1, AVX2, BMI2; OS saves XMM/YMM.
    constexpr uint32_t ecx = (1u<<20)|(1u<<12)|(1u<<26)|(1u<<27)|(1u<<28)|(1u<<29);
    constexpr uint32_t ebx = (1u<<3)|(1u<<5)|(1u<<8);
    return (f.leaf1_ecx & ecx) == ecx && (f.leaf7_ebx & ebx) == ebx && (f.xcr0 & 6) == 6;
}
inline std::wstring quote_windows_arg(const std::wstring &value) {
    std::wstring out = L"\"";
    size_t slashes = 0;
    for (wchar_t c : value) {
        if (c == L'\\') { ++slashes; continue; }
        out.append(slashes * (c == L'"' ? 2 : 1), L'\\');
        if (c == L'"') out += L'\\';
        out += c;
        slashes = 0;
    }
    out.append(slashes * 2, L'\\');
    return out + L'"';
}
#ifdef _WIN32
inline bool host_supports_avx2() {
    int regs[4];
    __cpuidex(regs, 0, 0);
    if (regs[0] < 7) return false;
    CpuFeatures f;
    __cpuidex(regs, 1, 0); f.leaf1_ecx = static_cast<uint32_t>(regs[2]);
    // Never execute XGETBV until the processor and OS both advertise XSAVE support.
    if ((f.leaf1_ecx & ((1u<<26)|(1u<<27))) != ((1u<<26)|(1u<<27))) return false;
    f.xcr0 = _xgetbv(0);
    __cpuidex(regs, 7, 0); f.leaf7_ebx = static_cast<uint32_t>(regs[1]);
    return supports_avx2(f);
}
inline std::wstring wide_utf8(const char *value) {
    int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value, -1, nullptr, 0);
    if (!count) throw std::runtime_error("SenseVoice argument is not valid UTF-8");
    std::wstring out(count, L'\0');
    if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value, -1, out.data(), count))
        throw std::runtime_error("Could not convert SenseVoice argument to UTF-16");
    out.pop_back();
    return out;
}
#endif
inline std::optional<int> dispatch_cpu(int argc, char **argv) {
#if defined(_WIN32) && !defined(PIANPIAN_AVX2)
    const char *forced = std::getenv("PIANPIAN_SENSEVOICE_CPU");
    if ((!forced || std::strcmp(forced, "baseline") != 0) && host_supports_avx2()) {
        std::wstring sibling(32768, L'\0');
        DWORD length = GetModuleFileNameW(nullptr, sibling.data(), static_cast<DWORD>(sibling.size()));
        if (!length || length == sibling.size()) throw std::runtime_error("Cannot locate the SenseVoice executable");
        sibling.resize(length);
        sibling = sibling.substr(0, sibling.find_last_of(L"\\/") + 1) + L"pianpian-sensevoice-avx2.exe";
        if (GetFileAttributesW(sibling.c_str()) != INVALID_FILE_ATTRIBUTES) {
            std::wstring command = quote_windows_arg(sibling);
            for (int i = 1; i < argc; ++i) command += L" " + quote_windows_arg(wide_utf8(argv[i]));
            STARTUPINFOW startup{}; startup.cb = sizeof(startup);
            startup.dwFlags = STARTF_USESTDHANDLES;
            startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
            startup.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
            startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);
            PROCESS_INFORMATION process{};
            if (!CreateProcessW(sibling.c_str(), command.data(), nullptr, nullptr, TRUE, CREATE_NO_WINDOW,
                                nullptr, nullptr, &startup, &process))
                throw std::runtime_error("Could not start the bundled SenseVoice AVX2 engine");
            CloseHandle(process.hThread);
            DWORD wait = WaitForSingleObject(process.hProcess, INFINITE), code = 1;
            bool ok = wait == WAIT_OBJECT_0 && GetExitCodeProcess(process.hProcess, &code);
            CloseHandle(process.hProcess);
            if (!ok) throw std::runtime_error("Could not wait for the SenseVoice AVX2 engine");
            return static_cast<int>(code);
        }
    }
#endif
#if defined(PIANPIAN_AVX2)
    const char *profile = "avx2";
#elif defined(_WIN32)
    const char *profile = "baseline";
#else
    const char *profile = "native";
#endif
    if (argc == 2 && std::strcmp(argv[1], "--cpu-profile") == 0) {
        std::printf("%s\n", profile);
        return 0;
    }
    std::fprintf(stderr, "[sensevoice] CPU profile: %s\n", profile);
    return std::nullopt;
}
} // namespace pianpian
