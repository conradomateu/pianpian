if(WIN32)
  enable_language(RC)
endif()

function(pianpian_version target)
  if(WIN32)
    file(READ "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../../.release-please-manifest.json" manifest)
    string(JSON version GET "${manifest}" ".")
    string(REPLACE "." "," version_numbers "${version}")
    configure_file("${CMAKE_CURRENT_FUNCTION_LIST_DIR}/version.rc.in"
                   "${CMAKE_CURRENT_BINARY_DIR}/${target}.rc" @ONLY)
    target_sources(${target} PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/${target}.rc")
  endif()
endfunction()
