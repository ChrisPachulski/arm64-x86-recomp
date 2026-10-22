// Layout probe, compiled for arm64 only (never run). sizeof/alignof go to __DATA,__probe; member offsets
// (Itanium data-member pointers = byte offset, 8 bytes each) to __DATA,__probeoff; names to __TEXT,__probenames.
#include <condition_variable>
#include <exception>
#include <functional>
#include <ios>
#include <locale>
#include <map>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

// Explicit instantiation may name private members; the friend getter hands the member pointer out.
template <class Tag, typename Tag::type P> struct Rob { friend constexpr typename Tag::type get(Tag) { return P; } };
#define STEAL(TAG, CLS, MEM, MT) \
  struct TAG { using type = MT CLS::*; friend constexpr type get(TAG); }; template struct Rob<TAG, &CLS::MEM>;

using SP = std::shared_ptr<int>;
using SC = std::__shared_count;
using SWC = std::__shared_weak_count;
using VI = std::vector<int>;
STEAL(sp_ptr, SP, __ptr_, int*)
STEAL(sp_cntrl, SP, __cntrl_, SWC*)
STEAL(sc_owners, SC, __shared_owners_, long)
STEAL(swc_weak, SWC, __shared_weak_owners_, long)
STEAL(v_begin, VI, __begin_, int*)
STEAL(v_end, VI, __end_, int*)

#define UNPAREN(...) __VA_ARGS__
#define TYPES(X) \
  X(string, (std::string)) X(wstring, (std::wstring)) X(vector_int, (std::vector<int>)) \
  X(shared_ptr_int, (std::shared_ptr<int>)) X(weak_ptr_int, (std::weak_ptr<int>)) \
  X(ctrl_shared_count, (std::__shared_count)) X(ctrl_shared_weak_count, (std::__shared_weak_count)) \
  X(ctrl_ptr_pointer_default_delete, (std::__shared_ptr_pointer<int*, std::default_delete<int>, std::allocator<int>>)) \
  X(ctrl_emplace_make_shared, (std::__shared_ptr_emplace<int, std::allocator<int>>)) \
  X(function_void, (std::function<void()>)) X(mutex, (std::mutex)) X(recursive_mutex, (std::recursive_mutex)) \
  X(condition_variable, (std::condition_variable)) X(locale, (std::locale)) X(ios_base, (std::ios_base)) \
  X(ostringstream, (std::ostringstream)) X(stringbuf, (std::stringbuf)) X(exception, (std::exception)) \
  X(runtime_error, (std::runtime_error)) X(logic_error, (std::logic_error)) \
  X(unordered_map_int_int, (std::unordered_map<int, int>)) X(map_int_int, (std::map<int, int>))
#define OFFS(X) X(sp_ptr) X(sp_cntrl) X(sc_owners) X(swc_weak) X(v_begin) X(v_end)

#define SV(n, T) sizeof(UNPAREN T), alignof(UNPAREN T),
#define SN(n, T) "sizeof." #n "\0alignof." #n "\0"
#define OV(t) t::type t;
#define OI(t) get(t{}),
#define ON(t) "offsetof." #t "\0"

struct Offs { OFFS(OV) };

extern "C" {
__attribute__((used, section("__DATA,__probe"))) unsigned long long probe_vals[] = { TYPES(SV) };
__attribute__((used, section("__DATA,__probeoff"))) Offs probe_offs = { OFFS(OI) };
__attribute__((used, section("__TEXT,__probenames"))) const char probe_names[] = TYPES(SN) OFFS(ON);
// Long-flag test shows up in the -O2 code of these two: ldrsb from #23 then a sign test.
__attribute__((used)) unsigned long probe_string_size(const std::string& s) { return s.size(); }
__attribute__((used)) const char* probe_string_data(const std::string& s) { return s.data(); }
}
