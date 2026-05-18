from __future__ import annotations


def package():
    return {'schema_version': '1',
 'provider': 'apt',
 'package_name': 'zstd',
 'package_version': '1.5.5+dfsg2-2build1.1',
 'requested_package': 'zstd',
 'with_deps': True,
 'context': {'distro': 'ubuntu', 'release': '24.04', 'arch': 'amd64'},
 'downloaded_at': '2026-05-18T04:47:08+00:00',
 'artifact_root': '/home/hyunsuk/ofpm/repos/main/apt/zstd/1.5.5_dfsg2-2build1.1/payload',
 'packages': [{'name': 'zstd',
               'version': '1.5.5+dfsg2-2build1.1',
               'filename': 'zstd_1.5.5+dfsg2-2build1.1_amd64.deb',
               'path': '/home/hyunsuk/ofpm/repos/main/apt/zstd/1.5.5_dfsg2-2build1.1/payload/pool/zstd_1.5.5+dfsg2-2build1.1_amd64.deb',
               'size': 644020},
              {'name': 'libc6',
               'version': '2.39-0ubuntu8.7',
               'filename': 'libc6_2.39-0ubuntu8.7_amd64.deb',
               'path': '/home/hyunsuk/ofpm/repos/main/apt/zstd/1.5.5_dfsg2-2build1.1/payload/pool/libc6_2.39-0ubuntu8.7_amd64.deb',
               'size': 3262920},
              {'name': 'libgcc-s1',
               'version': '14.2.0-4ubuntu2~24.04.1',
               'filename': 'libgcc-s1_14.2.0-4ubuntu2~24.04.1_amd64.deb',
               'path': '/home/hyunsuk/ofpm/repos/main/apt/zstd/1.5.5_dfsg2-2build1.1/payload/pool/libgcc-s1_14.2.0-4ubuntu2~24.04.1_amd64.deb',
               'size': 78392},
              {'name': 'liblz4-1',
               'version': '1.9.4-1build1.1',
               'filename': 'liblz4-1_1.9.4-1build1.1_amd64.deb',
               'path': '/home/hyunsuk/ofpm/repos/main/apt/zstd/1.5.5_dfsg2-2build1.1/payload/pool/liblz4-1_1.9.4-1build1.1_amd64.deb',
               'size': 63062},
              {'name': 'liblzma5',
               'version': '5.6.1+really5.4.5-1ubuntu0.2',
               'filename': 'liblzma5_5.6.1+really5.4.5-1ubuntu0.2_amd64.deb',
               'path': '/home/hyunsuk/ofpm/repos/main/apt/zstd/1.5.5_dfsg2-2build1.1/payload/pool/liblzma5_5.6.1+really5.4.5-1ubuntu0.2_amd64.deb',
               'size': 127160},
              {'name': 'libstdc++6',
               'version': '14.2.0-4ubuntu2~24.04.1',
               'filename': 'libstdc++6_14.2.0-4ubuntu2~24.04.1_amd64.deb',
               'path': '/home/hyunsuk/ofpm/repos/main/apt/zstd/1.5.5_dfsg2-2build1.1/payload/pool/libstdc++6_14.2.0-4ubuntu2~24.04.1_amd64.deb',
               'size': 792064},
              {'name': 'zlib1g',
               'version': '1:1.3.dfsg-3.1ubuntu2.1',
               'filename': 'zlib1g_1%3a1.3.dfsg-3.1ubuntu2.1_amd64.deb',
               'path': '/home/hyunsuk/ofpm/repos/main/apt/zstd/1.5.5_dfsg2-2build1.1/payload/pool/zlib1g_1%3a1.3.dfsg-3.1ubuntu2.1_amd64.deb',
               'size': 62850},
              {'name': 'gcc-14-base',
               'version': '14.2.0-4ubuntu2~24.04.1',
               'filename': 'gcc-14-base_14.2.0-4ubuntu2~24.04.1_amd64.deb',
               'path': '/home/hyunsuk/ofpm/repos/main/apt/zstd/1.5.5_dfsg2-2build1.1/payload/pool/gcc-14-base_14.2.0-4ubuntu2~24.04.1_amd64.deb',
               'size': 51014}],
 'apt_metadata': {'Package': 'zstd',
                  'Source': 'libzstd',
                  'Priority': 'optional',
                  'Section': 'utils',
                  'Installed-Size': '1802',
                  'Maintainer': 'Ubuntu Developers <ubuntu-devel-discuss@lists.ubuntu.com>',
                  'Architecture': 'amd64',
                  'Version': '1.5.5+dfsg2-2build1.1',
                  'Depends': 'libc6 (>= 2.34), libgcc-s1 (>= 3.3.1), liblz4-1 (>= 1.8.0), liblzma5 '
                             '(>= 5.1.1alpha+20120614), libstdc++6 (>= 12), zlib1g (>= 1:1.1.4)',
                  'Filename': 'pool/main/libz/libzstd/zstd_1.5.5+dfsg2-2build1.1_amd64.deb',
                  'Size': '644020',
                  'MD5sum': '54ec61e91a6de11f5346ccc492767a53',
                  'SHA1': 'b3cb09cfac8a2c00fcabcce2d303077324c1c6ed',
                  'SHA256': 'd7667f83e3a2caeaaecaca464d542ee6ccf537259a479622796c84afc96d6032',
                  'SHA512': '3874d539d1e98dcad532651d9410a01a2fe2285f156d20e5a11b2347b10e0894e863009f86211eded75c949a983f9f429c9c26747739193bb28a1912156c7a3b',
                  'Homepage': 'https://github.com/facebook/zstd',
                  'Description': 'fast lossless compression algorithm -- CLI tool',
                  'Description-md5': 'd2e4d40bb07cc70b5a32d3b4a9b5f53d',
                  'Multi-Arch': 'foreign',
                  'Original-Maintainer': 'RPM packaging team <team+pkg-rpm@tracker.debian.org>',
                  'Origin': 'Ubuntu',
                  'Bugs': 'https://bugs.launchpad.net/ubuntu/+filebug',
                  'Task': 'ubuntu-desktop-minimal, ubuntu-desktop, ubuntu-live, cloud-image, '
                          'cloud-image, server, ubuntu-server-raspi, kubuntu-desktop, '
                          'kubuntu-full, kubuntu-live, xubuntu-minimal, xubuntu-desktop, '
                          'xubuntu-live, lubuntu-desktop, lubuntu-live, ubuntustudio-desktop, '
                          'ubuntustudio-dvd-live, ubuntukylin-desktop, ubuntukylin-desktop, '
                          'ubuntukylin-live, ubuntukylin-desktop-minimal, ubuntu-mate-core, '
                          'ubuntu-mate-desktop, ubuntu-mate-live, ubuntu-budgie-desktop-minimal, '
                          'ubuntu-budgie-desktop, ubuntu-budgie-live, ubuntu-budgie-desktop-raspi, '
                          'ubuntu-unity-desktop, ubuntu-unity-live, '
                          'edubuntu-desktop-gnome-minimal, edubuntu-desktop-gnome, '
                          'edubuntu-dvd-live, edubuntu-desktop-gnome-raspi, edubuntu-live, '
                          'ubuntucinnamon-desktop-minimal, ubuntucinnamon-desktop, '
                          'ubuntucinnamon-desktop, ubuntucinnamon-live, '
                          'ubuntucinnamon-desktop-raspi'}}
