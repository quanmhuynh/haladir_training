import modal
import subprocess
import tempfile
import os


image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install(
        "build-essential",
        "gcc",
        "make",
    )
)

app = modal.App("comp_check", image=image)


@app.function(
    max_containers=50,
    timeout=120,
)
def check_compilation(c_code: str) -> bool:
    print(f"\n{'='*80}")
    print(f"CHECK_COMPILATION")
    print(f"{'='*80}")
    print(f"Input code type: {type(c_code)}")
    print(f"Input code length: {len(c_code) if c_code else 0} chars")
    print(f"\n--- INPUT CODE (first 500 chars) ---")
    if c_code:
        print(c_code[:500])
        if len(c_code) > 500:
            print(f"... (truncated, total length: {len(c_code)} chars)")
    else:
        print("(empty)")
    print(f"--- END INPUT CODE ---\n")
    
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".c", delete=False) as f:
            f.write(c_code)
            temp_filename = f.name

        print(f"Compiling: {temp_filename}")
        print(f"Timeout: 30 seconds")
        try:
            result = subprocess.run(
                ["gcc", "-c", temp_filename, "-o", "/dev/null"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            compile_timeout = False
        except subprocess.TimeoutExpired as e:
            print(f"\n--- COMPILATION TIMEOUT ---")
            print(f"Compilation timed out after 30 seconds")
            print(f"Timeout error: {e}")
            print(f"--- END COMPILATION TIMEOUT ---\n")
            compile_timeout = True
            result = None

        if compile_timeout:
            os.unlink(temp_filename)
            print(f"✗ Compilation TIMEOUT")
            print(f"\n{'='*80}")
            print(f"FAILED - Compilation timed out")
            print(f"{'='*80}\n")
            return False

        print(f"Compilation return code: {result.returncode}")
        print(f"\n--- GCC STDOUT ---")
        print(result.stdout if result.stdout else "(empty)")
        print(f"--- END GCC STDOUT ---")
        if result.stderr:
            print(f"\n--- GCC STDERR ---")
            print(result.stderr)
            print(f"--- END GCC STDERR ---")
        print()

        os.unlink(temp_filename)
        if result.returncode == 0:
            print(f"✓ Compilation SUCCESSFUL")
            print(f"\n{'='*80}")
            print(f"SUCCESS - Code compiles")
            print(f"{'='*80}\n")
            return True
        else:
            print(f"✗ Compilation FAILED")
            print(f"\n{'='*80}")
            print(f"FAILED - Compilation error")
            print(f"{'='*80}\n")
            return False
    except Exception as e:
        print(f"\n--- EXCEPTION ---")
        print(f"Compilation check error: {e}")
        print(f"Error type: {type(e).__name__}")
        print(f"--- END EXCEPTION ---\n")
        print(f"\n{'='*80}")
        print(f"FAILED - Exception occurred")
        print(f"{'='*80}\n")
        return False

