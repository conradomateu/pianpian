#define main alignment_program_main
#include "main.cpp"
#undef main

static void require(bool ok) {if(!ok)throw std::runtime_error("Native alignment regression");}
template<class F>static void rejects(F f){bool failed=false;try{f();}catch(const std::exception&){failed=true;}require(failed);}
int main() {
    require(unhex("e4b8ade696870a")==u8"中文\n");
    require(unhex("4142ff")==std::string("AB\xff",3));
    rejects([]{unhex("");});rejects([]{unhex("a");});rejects([]{unhex("zz");});
    rejects([]{unhex(std::string(131074,'0'));});
    Capture state{"l_out-7",1536,{},true};ggml_tensor tensor{};
    std::strcpy(tensor.name,"l_out-7");
    require(capture(&tensor,true,&state));
    std::strcpy(tensor.name,"l_out-8");require(!capture(&tensor,true,&state));
    std::strcpy(tensor.name,"l_out-7");tensor.type=GGML_TYPE_F16;
    require(!capture(&tensor,false,&state)&&!state.valid);
    rejects([&]{emit(nullptr,{1},state);});
    state={"l_out-7",1,{std::nanf("")},true};
    rejects([&]{emit(nullptr,{1},state);});
    require(unhex("3c7c706c616d6f3a626f737c3e")=="<|plamo:bos|>");
    std::cout << "UTF-8 framing, tensor selection, shape and finite checks passed\n";
}
