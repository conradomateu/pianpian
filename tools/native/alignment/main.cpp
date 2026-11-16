// PLaMo word-link vectors from the existing pinned llama.cpp runtime, with no extra model.
#include "llama.h"
#include "ggml-backend.h"
#include <cmath>
#include <cstring>
#include <filesystem>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#endif

#define API_LIST(X) \
 X(ggml_backend_load_all_from_path) X(ggml_backend_tensor_get) \
 X(llama_backend_init) X(llama_backend_free) X(llama_model_default_params) \
 X(llama_context_default_params) X(llama_model_load_from_file) X(llama_init_from_model) \
 X(llama_model_get_vocab) X(llama_model_n_layer) X(llama_model_n_embd) X(llama_tokenize) \
 X(llama_token_to_piece) X(llama_get_memory) X(llama_memory_clear) X(llama_batch_init) \
 X(llama_batch_free) X(llama_decode) X(llama_free) X(llama_model_free)
#define DECLARE(name) static decltype(&name) p_##name = nullptr;
API_LIST(DECLARE)
#undef DECLARE

static std::vector<void*> libraries;
static void* symbol(const char* name) {
    for(auto h:libraries) {
#ifdef _WIN32
        auto p=reinterpret_cast<void*>(GetProcAddress(static_cast<HMODULE>(h),name));
#else
        auto p=dlsym(h,name);
#endif
        if(p)return p;
    }
    throw std::runtime_error(std::string("Pinned llama.cpp runtime lacks ")+name);
}
static void load_runtime(const std::string& directory) {
    const auto root=std::filesystem::absolute(std::filesystem::u8path(directory));
#ifdef _WIN32
    const char* names[]={"ggml-base.dll","ggml.dll","llama.dll"};
#elif defined(__APPLE__)
    const char* names[]={"libggml-base.dylib","libggml.dylib","libllama.dylib"};
#else
    const char* names[]={"libggml-base.so","libggml.so","libllama.so"};
#endif
    for(auto name:names) {
        const auto path=root/name;
#ifdef _WIN32
        void* h=LoadLibraryExW(path.c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
#else
        void* h=dlopen(path.c_str(),RTLD_NOW|RTLD_GLOBAL);
#endif
        if(!h)throw std::runtime_error("Cannot load pinned translation library: "+path.u8string());
        libraries.push_back(h);
    }
#define LOAD(name) p_##name=reinterpret_cast<decltype(p_##name)>(symbol(#name));
    API_LIST(LOAD)
#undef LOAD
    p_ggml_backend_load_all_from_path(directory.c_str());
}

static std::string unhex(const std::string& line) {
    if(line.empty() || line.size()%2 || line.size()>131072)throw std::runtime_error("Input must be nonempty UTF-8 hex, at most 65536 bytes");
    auto digit=[](char c)->int { if(c>='0'&&c<='9')return c-'0';if(c>='a'&&c<='f')return c-'a'+10;if(c>='A'&&c<='F')return c-'A'+10;throw std::runtime_error("Invalid input hex"); };
    std::string text; text.reserve(line.size()/2);
    for(size_t i=0;i<line.size();i+=2)text.push_back(char(digit(line[i])*16+digit(line[i+1])));
    return text;
}
struct Capture {
    std::string name;
    int dimensions;
    std::vector<float> values;
    bool valid=true;
};
static bool capture(ggml_tensor* tensor,bool ask,void* userdata) {
    auto& result=*static_cast<Capture*>(userdata);
    const bool selected=result.name==tensor->name;
    if(ask)return selected;
    if(!selected)return true;
    if(tensor->type!=GGML_TYPE_F32 || tensor->ne[0]!=result.dimensions || tensor->ne[1]<1 ||
       tensor->nb[0]!=sizeof(float) || tensor->nb[1]!=sizeof(float)*result.dimensions || tensor->ne[2]!=1 || tensor->ne[3]!=1) {
        result.valid=false;return false;
    }
    const size_t count=static_cast<size_t>(tensor->ne[0])*tensor->ne[1];
    if(count>4096u*result.dimensions || result.values.size()+count>4096u*result.dimensions) {result.valid=false;return false;}
    try {
        const auto old=result.values.size();result.values.resize(old+count);
        p_ggml_backend_tensor_get(tensor,result.values.data()+old,0,count*sizeof(float));
    } catch(...) {result.valid=false;return false;}
    return true;
}
static std::vector<char> piece(const llama_vocab* vocab,llama_token token) {
    std::vector<char> out(128);
    int n=p_llama_token_to_piece(vocab,token,out.data(),out.size(),0,true);
    if(n<0){out.resize(-n);n=p_llama_token_to_piece(vocab,token,out.data(),out.size(),0,true);}
    if(n<0)throw std::runtime_error("Could not decode token piece");out.resize(n);return out;
}
static void emit(const llama_vocab* vocab,const std::vector<llama_token>& tokens,const Capture& state) {
    if(!state.valid || state.values.size()!=tokens.size()*state.dimensions)throw std::runtime_error("Incomplete middle-layer token vectors");
    for(auto x:state.values)if(!std::isfinite(x))throw std::runtime_error("Non-finite middle-layer vector");
    // Bytes preserve partial UTF-8 tokens without emitting malformed JSON strings.
    std::cout << "{\"tokens\":[";
    for(size_t i=0;i<tokens.size();i++) {
        if(i)std::cout << ',';
        auto bytes=piece(vocab,tokens[i]);std::cout << "{\"id\":" << tokens[i] << ",\"piece\":[";
        for(size_t j=0;j<bytes.size();j++){if(j)std::cout << ',';std::cout << static_cast<unsigned>(static_cast<unsigned char>(bytes[j]));}
        std::cout << "]}";
    }
    std::cout << "],\"vectors\":[" << std::setprecision(9);
    for(size_t i=0;i<tokens.size();i++) {
        if(i)std::cout << ',';std::cout << '[';
        for(int j=0;j<state.dimensions;j++){if(j)std::cout << ',';std::cout << state.values[i*state.dimensions+j];}
        std::cout << ']';
    }
    std::cout << "]}" << std::endl;
}
int main(int argc,char**argv) {
    llama_model* model=nullptr;llama_context* ctx=nullptr;bool initialized=false;
    try {
        std::string runtime,filename;int layer=7;
        for(int i=1;i<argc;i++) {
            std::string arg=argv[i];
            if(arg=="--help") {std::cout << "Pianpian alignment (llama.cpp b11851): --runtime DIR --model GGUF [--layer 7]\nstdin: one hex-encoded UTF-8 prompt per line; stdout: JSON token pieces and middle-layer vectors. CPU only.\n";return 0;}
            if(arg=="--version") {std::cout << "pianpian-align 1 (llama.cpp b11851 ABI)\n";return 0;}
            if(i+1==argc)throw std::runtime_error("Missing option value");
            if(arg=="--runtime")runtime=argv[++i];
            else if(arg=="--model")filename=argv[++i];
            else if(arg=="--layer") {std::string value=argv[++i];size_t used=0;layer=std::stoi(value,&used);if(used!=value.size())throw std::runtime_error("Invalid layer");}
            else throw std::runtime_error("Unknown option: "+arg);
        }
        if(runtime.empty()||filename.empty())throw std::runtime_error("--runtime and --model are required");
        load_runtime(runtime);p_llama_backend_init();initialized=true;
        auto mp=p_llama_model_default_params();mp.n_gpu_layers=0;
        model=p_llama_model_load_from_file(filename.c_str(),mp);if(!model)throw std::runtime_error("Cannot load PLaMo model");
        const int dimensions=p_llama_model_n_embd(model);
        if(layer<0||layer>=p_llama_model_n_layer(model)-1||dimensions<=0)throw std::runtime_error("Invalid alignment layer or model shape");
        Capture state{"l_out-"+std::to_string(layer),dimensions,{},true};
        auto cp=p_llama_context_default_params();cp.n_ctx=4096;cp.n_batch=4096;cp.n_ubatch=512;cp.n_threads=4;cp.n_threads_batch=4;
        cp.cb_eval=capture;cp.cb_eval_user_data=&state;
        ctx=p_llama_init_from_model(model,cp);if(!ctx)throw std::runtime_error("Cannot create alignment context");
        const auto* vocab=p_llama_model_get_vocab(model);
        std::string line;
        while(std::getline(std::cin,line)) {
            if(!line.empty()&&line.back()=='\r')line.pop_back();
            auto text=unhex(line);std::vector<llama_token> tokens(4096);
            int n=p_llama_tokenize(vocab,text.data(),text.size(),tokens.data(),tokens.size(),false,true);
            if(n<1||n>4096)throw std::runtime_error("Alignment prompt exceeds 4096 tokens or is empty");tokens.resize(n);
            p_llama_memory_clear(p_llama_get_memory(ctx),true);state.values.clear();state.valid=true;
            auto batch=p_llama_batch_init(n,0,1);batch.n_tokens=n;
            for(int i=0;i<n;i++){batch.token[i]=tokens[i];batch.pos[i]=i;batch.n_seq_id[i]=1;batch.seq_id[i][0]=0;batch.logits[i]=(i==n-1);}
            int status=p_llama_decode(ctx,batch);p_llama_batch_free(batch);
            if(status!=0)throw std::runtime_error("Alignment inference failed");emit(vocab,tokens,state);
        }
        if(std::cin.bad())throw std::runtime_error("Could not read alignment prompts");
        p_llama_free(ctx);p_llama_model_free(model);p_llama_backend_free();return 0;
    } catch(const std::exception& e) {
        std::cerr << "Pianpian alignment: " << e.what() << '\n';
        if(ctx)p_llama_free(ctx);if(model)p_llama_model_free(model);if(initialized)p_llama_backend_free();return 1;
    }
}
