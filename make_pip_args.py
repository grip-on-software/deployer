"""
Generate additional pip arguments based on a PyPI registry index URL.

Copyright 2017-2020 ICTU
Copyright 2017-2022 Leiden University
Copyright 2017-2023 Leon Helwerda

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import urllib.parse
import sys
import tempfile
import certifi

def main(args):
    """
    Main entry point.
    """

    if not args:
        return

    registry_url = args[0]
    certificate_path = args[1] if len(args) > 1 else None

    # Parse URL: does it have a protocol? Get domain name without port/proto.
    if registry_url.startswith('http://') or registry_url.startswith('https://'):
        host = urllib.parse.urlsplit(registry_url).hostname
    else:
        host = registry_url.split(':', 1)[0]
        registry_url = f'http://{registry_url}'

    arguments = {
        'extra-index-url': registry_url,
        'trusted-host': host
    }

    if certificate_path is not None:
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
            bundle_path = certifi.where()
            with open(bundle_path, 'r', encoding='utf-8') as bundle_file:
                for line in bundle_file:
                    temp_file.write(line)

            # Append the certificate to the temporary file
            with open(certificate_path, 'r', encoding='utf-8') as certificate_file:
                for line in certificate_file:
                    temp_file.write(line)

            arguments['cert'] = temp_file.name

    print(' '.join(f'--{key} {value}' for key, value in arguments.items()))

if __name__ == '__main__':
    main(sys.argv[1:])
