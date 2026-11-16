#include "cpu_dispatch.h"
#include <cassert>
int main() {
    using namespace pianpian;
    CpuFeatures ready{(1u<<20)|(1u<<12)|(1u<<26)|(1u<<27)|(1u<<28)|(1u<<29),
                      (1u<<3)|(1u<<5)|(1u<<8), 6};
    assert(supports_avx2(ready));
    for (unsigned bit : {20, 12, 26, 27, 28, 29}) {
        auto missing = ready; missing.leaf1_ecx &= ~(1u<<bit); assert(!supports_avx2(missing));
    }
    for (unsigned bit : {3, 5, 8}) {
        auto missing = ready; missing.leaf7_ebx &= ~(1u<<bit); assert(!supports_avx2(missing));
    }
    for (uint64_t state : {0, 2, 4}) {
        auto missing = ready; missing.xcr0 = state; assert(!supports_avx2(missing));
    }
    assert(quote_windows_arg(L"") == L"\"\"");
    assert(quote_windows_arg(L"中文 空格") == L"\"中文 空格\"");
    assert(quote_windows_arg(L"a\\b") == L"\"a\\b\"");
    assert(quote_windows_arg(L"end\\") == L"\"end\\\\\"");
    assert(quote_windows_arg(L"a\"b") == L"\"a\\\"b\"");
    assert(quote_windows_arg(L"a\\\"b") == L"\"a\\\\\\\"b\"");
}
