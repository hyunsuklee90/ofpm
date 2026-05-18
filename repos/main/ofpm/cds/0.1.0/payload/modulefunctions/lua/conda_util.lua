local conda_util = {}

function conda_util.setup(conda_dir)
    -- 모듈 패밀리 설정
    family("anaconda")

    -- 1. Base Conda 설치 경로 찾기 (가장 중요!)
    --    시스템에 ANACONDA_HOME 이나 CONDA_ROOT 같은 환경 변수를 사용하거나,
    --    실제 base anaconda (or miniconda) 설치 경로를 직접 지정합니다.
    local conda_base_dir = os.getenv("CONDA_ROOT") or "/opt/anaconda3"

    -- 2. Base Conda에 있는 conda.sh 스크립트 경로 설정
    local conda_sh = pathJoin(conda_base_dir, "etc", "profile.d", "conda.sh")

    -- conda.sh 파일이 존재하는지 확인
    if not isFile(conda_sh) then
        LmodError("Conda shell script not found. Looked in: ", conda_sh)
        return
    end

    -- 3. module load 시 `conda activate` 실행
    --    먼저 base의 conda.sh를 불러온 후, 원하는 환경(conda_dir)을 활성화합니다.
    execute{
        cmd   = "source " .. conda_sh .. " && conda activate " .. conda_dir,
        modeA = {"load"}
    }

    -- 4. module unload 시 `conda deactivate` 실행
    execute{
        cmd   = "source " .. conda_sh .. " && conda deactivate",
        modeA = {"unload"}
    }
end

return conda_util
