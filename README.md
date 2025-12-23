This project has been created as part of the 42 curriculum by <vinpache>.

🌐 NetPractice

Este projeto é uma imersão prática nos fundamentos de redes de computadores. O objetivo aqui não foi apenas "passar de fase", mas entender como a Internet realmente conecta dispositivos, desde a configuração de um simples IP até o roteamento complexo entre sub-redes.

📝 Description

O NetPractice é um exercício prático desenhado para ensinar os conceitos básicos de redes através de uma interface gamificada. O desafio consiste em consertar redes quebradas em 10 níveis de dificuldade crescente.

Em cada nível, recebo uma topologia de rede com problemas de configuração. Meu trabalho é ajustar endereços IP, Máscaras de Sub-rede (Netmasks) e Tabelas de Roteamento para garantir que determinados hosts consigam se comunicar (fazer o famoso "ping") entre si ou com a Internet.

Principais desafios enfrentados:

Evitar conflitos de IP em redes locais.

Configurar roteadores para atuarem como Gateways.

Calcular sub-redes (Subnetting e VLSM) para otimizar o uso de endereços.

Definir rotas estáticas para garantir o caminho de ida e, crucialmente, o caminho de volta dos pacotes.

🚀 Instructions

Para rodar o ambiente de treinamento e testar as configurações, siga os passos abaixo:

1. Instalação e Execução

Este projeto roda diretamente no navegador, sem necessidade de compilação complexa.

Clone este repositório ou baixe os arquivos.

Localize o arquivo index.html na pasta raiz.

Abra o index.html no seu navegador web preferido (Chrome, Firefox, etc.).

Na tela de login, insira seu login da intra (ex: ol) para garantir que os exercícios sejam gerados com a seed correta para você.

Clique em Start!.

2. Como Jogar

Selecione o nível desejado (são 10 níveis no total, do Level 1 ao Level 10).

Modifique os campos de texto (IPs, Máscaras, Rotas) para corrigir a rede.

Clique em Check again para validar. Se tudo ficar verde ("Status: OK"), você passou!

3. Exportando Configurações

Para salvar o progresso:

Após completar um nível, clique no botão Get my config.

Isso baixará um arquivo (ex: level1.net).

Este arquivo deve ser salvo na raiz deste repositório para submissão.

📦 Submission

Conforme os requisitos do projeto, este repositório contém os 10 arquivos de configuração exportados, um para cada nível completado com sucesso.

Os arquivos estão localizados na raiz do repositório:

level1.net

level2.net

...

level10.net

Nota: Durante a avaliação (defense), serei testado em 3 níveis aleatórios e precisarei resolvê-los ao vivo, provando que entendi a lógica por trás das configurações.

📚 Resources & Concepts

Para resolver estes desafios, foi necessário estudar e aplicar os seguintes conceitos fundamentais de redes:

TCP/IP Addressing: Entender a estrutura do IPv4 (4 octetos) e como ele identifica unicamente um dispositivo na rede.

Subnet Mask (Máscara de Sub-rede): Fundamental para definir o tamanho da rede e distinguir a parte "Rede" da parte "Host". Usei muito a notação CIDR (ex: /24, /28).

Default Gateway: A porta de saída da rede local. Sem configurar isso corretamente nos Hosts, eles não conseguem falar com ninguém fora de casa.

Routers & Switches:

Switches: Conectam dispositivos na mesma rede (Layer 2).

Routers: Conectam redes diferentes (Layer 3) e tomam decisões de roteamento.

OSI Layers: Entender que o IP opera na Camada 3 (Rede) foi essencial para diagnosticar problemas de conectividade.

Roteamento Estático (Next Hop): Aprendi que a internet não é mágica; precisamos dizer explicitamente ao roteador "para chegar na rede X, jogue o pacote para o vizinho Y".

Referências Úteis

Cisco Networking Academy - Subnetting Practice

IP Subnet Calculator - Ótimo para verificar cálculos de VLSM.

Documentação oficial do NetPractice (PDF do subject).

🤖 AI Usage

Durante o desenvolvimento deste projeto, utilizei ferramentas de Inteligência Artificial para auxiliar no aprendizado, seguindo as diretrizes éticas da 42.

Como a IA foi utilizada:

Clarificação de Conceitos: Usei IA para explicar a diferença prática entre máscaras /24 e /28 e como o Variable Length Subnet Masking (VLSM) funciona na prática (especialmente nos níveis 7 e 8).

Debugging de Lógica: Quando encontrava erros como "No reverse way", pedi à IA para analisar a lógica do fluxo de pacotes (ida e volta) para entender onde o roteamento estava falhando.

Revisão de Documentação: Auxílio na estruturação e revisão deste README para garantir clareza e conformidade com os requisitos.

A IA foi usada como uma tutora para reforçar o entendimento, mas todas as configurações finais e a lógica de resolução dos níveis foram executadas e validadas por mim.
